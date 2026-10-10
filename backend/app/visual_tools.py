"""Pinned CopilotKit 1.55.2-next.1 frontend tool contract for the headless host.

Upstream's React provider normally advertises this tool. Open Learn owns the
composer, so it supplies that same AG-UI definition server-side instead.
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
            },
            'additionalProperties': False,
            'required':['html'],
        },
    }]
