"""Parse generated JavaScript without executing it; repair only literal JSON encoding."""
import json
import re
import subprocess
from html.parser import HTMLParser


class VisualCodeError(ValueError):
    """A fixed error code (str) plus a bounded, model-facing diagnostic."""
    def __init__(self,code,detail=''):
        super().__init__(code)
        self.detail=detail[:900]


def created_ids(code):
    """Ids the script assigns itself (element.id, setAttribute, markup strings)."""
    return set(re.findall(r"""(?:\.id\s*=\s*['"`]|setAttribute\(\s*['"]id['"]\s*,\s*['"`]|\bid\s*=\s*\\?['"])([A-Za-z][A-Za-z0-9_-]*)""",code))


def normalize_dom_targets(html,code,strict=True):
    """Repair an exact unique class-to-id mismatch.

    With ``strict`` (runtime verification unavailable) an id that is neither in
    the html nor assigned by the script is rejected. Otherwise runtime
    verification observes the real lookup, so valid dynamic DOM is not refused.
    """
    targets=set(re.findall(r"(?:document\.getElementById|\bL\.map)\(\s*['\"]([A-Za-z][A-Za-z0-9_-]*)['\"]",code))-created_ids(code)
    ids=set();classes={}
    class Elements(HTMLParser):
        def handle_starttag(self,tag,attrs):
            values=dict(attrs)
            if values.get('id'):ids.add(values['id'])
            for name in values.get('class','').split():classes.setdefault(name,[]).append((self.get_starttag_text(),values.get('id')))
    Elements().feed(html)
    for target in targets-ids:
        matches=classes.get(target,[])
        if (len(matches)!=1 or matches[0][1]) and not strict:
            continue
        if len(matches)!=1 or matches[0][1]:
            raise VisualCodeError('visual_missing_dom_target:'+target,
                f'JavaScript looks up the element id "{target}", but the html has no element with id="{target}". Use every id exactly as declared in html.')
        original=matches[0][0]
        html=html.replace(original,original[:-1]+f' id="{target}">',1)
    return html


def normalize_json_literals(code):
    # Some models put literal line breaks in JSON.parse('...'). Decode valid
    # JSON and re-encode as a JS object literal; never evaluate source text.
    def replace(match):
        raw=match.group(1)
        if '\n' not in raw:return match.group(0)
        try:return '('+json.dumps(json.loads(raw),ensure_ascii=True)+')'
        except (ValueError,TypeError):return match.group(0)
    return re.sub(r"JSON\.parse\('([\s\S]*?)'\)",replace,code)


def validate_visual_code(content,strict_dom=True):
    result=dict(content)
    result['jsFunctions']=normalize_json_literals(result.get('jsFunctions',''))
    result['jsExpressions']=[normalize_json_literals(value) for value in result.get('jsExpressions',[])]
    source=result['jsFunctions']+'\n(async()=>{\n'+';\n'.join(result['jsExpressions'])+'\n})();'
    if result.get('html'):
        result['html']=[normalize_dom_targets(''.join(result['html']),source,strict_dom)]
    try:
        # Explicit UTF-8: the platform default (cp1252 on Windows) cannot encode
        # common visual text such as Greek letters, arrows or emoji.
        checked=subprocess.run(['node','--check'],input=source,text=True,encoding='utf-8',capture_output=True,timeout=10)
    except (OSError,subprocess.TimeoutExpired):
        raise ValueError('visual_code_validator_unavailable') from None
    if checked.returncode:
        # node --check prints the offending line, a caret and the message.
        # Line numbers refer to jsFunctions followed by the expressions.
        lines=[line for line in checked.stderr.splitlines() if line.strip() and not line.startswith(('Node.js','    at '))]
        raise VisualCodeError('visual_invalid_javascript','JavaScript syntax error:\n'+'\n'.join(lines[:8]))
    return result
