import pytest
from backend.app.browser_assistant.executors.cloud import valid_live_view_url

@pytest.mark.parametrize('url',[
 'https://debug.browserbase.com/session?token=synthetic',
 'https://www.browserbase.com/devtools-fullscreen?token=synthetic',
 'https://www.browserbase.com:443/devtools-fullscreen',
])
def test_exact_provider_live_view_hosts(url):
 assert valid_live_view_url(url)

@pytest.mark.parametrize('url',[
 'http://www.browserbase.com/devtools-fullscreen',
 'https://www.browserbase.com.evil.example/',
 'https://evil.example/?next=https://www.browserbase.com',
 'https://user:secret@www.browserbase.com/',
 'https://www.browserbase.com:8443/',
 'https://www.browserbase.com:invalid/',
 'javascript:alert(1)',None,
])
def test_live_view_rejects_untrusted_or_malformed_urls(url):
 assert not valid_live_view_url(url)
