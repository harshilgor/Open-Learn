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


def test_provider_validates_every_issued_link_and_requests_short_expiry():
 from backend.app.browser_assistant.executors.cloud import BrowserbaseProvider
 provider=BrowserbaseProvider()
 calls=[]
 def request(method,path,data=None):
  calls.append((method,path))
  return {'debuggerFullscreenUrl':'https://www.browserbase.com/devtools-fullscreen?debug=synthetic'}
 provider.request=request
 assert provider.live_view('synthetic-session').startswith('https://www.browserbase.com/')
 assert calls==[('GET','sessions/synthetic-session/debug?expiresIn=60')]
 provider.request=lambda *args,**kwargs:{'debuggerFullscreenUrl':'https://evil.example/'}
 with pytest.raises(ValueError):provider.live_view('synthetic-session')
