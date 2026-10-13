"""Pinned CopilotKit 1.55.2-next.1 frontend tool contract for the headless host.

Upstream's React provider normally advertises this tool. Open Learn owns the
composer, so it supplies that same AG-UI definition server-side instead. The
optional ``editOf`` argument is an Open Learn addition read from the tool-call
arguments by the orchestrator; it is not part of the rendered activity.
"""

def renderer_tools():
    return [{
        'name': 'generateSandboxedUi',
        'description': 'Generate an interactive visual inside an isolated Websandbox. Emit initialHeight, placeholderMessages, css, html, jsFunctions, jsExpressions in that order. CSS contains all styles. HTML is body markup without script/style blocks. JavaScript runs as classic scripts; put asynchronous library imports inside functions and call them from expressions. Use the host theme variables and accessible labels. The host handles rendering and persistence.',
        'parameters': {
            'type': 'object',
            'properties': {
                'initialHeight': {'type': 'number'},
                'placeholderMessages': {'type': 'array', 'items': {'type': 'string'}},
                'css': {'type': 'string'}, 'html': {'type': 'string', 'minLength':1},
                'jsFunctions': {'type': 'string'},
                'jsExpressions': {'type': 'array', 'items': {'type': 'string'}},
                'editOf': {'type': 'string', 'description': 'Set to editTarget.id when this artifact is a revised version of that '
                           'existing visual. Omit it for a new, unrelated visual.'},
            },
            'additionalProperties': False,
            'required':['html'],
        },
    }]
