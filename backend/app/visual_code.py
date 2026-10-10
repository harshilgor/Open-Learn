"""Parse generated JavaScript without executing it; repair only literal JSON encoding."""
import json
import re
import subprocess
from html.parser import HTMLParser


def normalize_dom_targets(html,code):
    targets=set(re.findall(r"(?:document\.getElementById|\bL\.map)\(\s*['\"]([A-Za-z][A-Za-z0-9_-]*)['\"]",code))
    ids=set();classes={}
    class Elements(HTMLParser):
        def handle_starttag(self,tag,attrs):
            values=dict(attrs)
            if values.get('id'):ids.add(values['id'])
            for name in values.get('class','').split():classes.setdefault(name,[]).append((self.get_starttag_text(),values.get('id')))
    Elements().feed(html)
    for target in targets-ids:
        matches=classes.get(target,[])
        if len(matches)!=1 or matches[0][1]:raise ValueError('visual_missing_dom_target:'+target)
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


def validate_visual_code(content):
    result=dict(content)
    result['jsFunctions']=normalize_json_literals(result.get('jsFunctions',''))
    result['jsExpressions']=[normalize_json_literals(value) for value in result.get('jsExpressions',[])]
    source=result['jsFunctions']+'\n(async()=>{\n'+';\n'.join(result['jsExpressions'])+'\n})();'
    if result.get('html'):
        result['html']=[normalize_dom_targets(''.join(result['html']),source)]
    try:
        checked=subprocess.run(['node','--check'],input=source,text=True,capture_output=True,timeout=10)
    except (OSError,subprocess.TimeoutExpired):
        raise ValueError('visual_code_validator_unavailable') from None
    if checked.returncode:
        raise ValueError('visual_invalid_javascript')
    return result
