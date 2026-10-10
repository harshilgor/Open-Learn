"""Supervise private visual sidecars and the public API in one deployment unit."""
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sidecar_environment():
    allowed = {'PATH','HOME','TMP','TEMP','SYSTEMROOT','LANG','PYTHONPATH',
               'OPENLEARN_VISUAL_INTERNAL_SECRET','OPENLEARN_VISUAL_MODEL','OPENLEARN_VISUAL_JEV_MODEL','OPENROUTER_MODEL'}
    result = {key:value for key,value in os.environ.items() if key in allowed}
    result['OPENLEARN_OPENINTELLIGENTUI_ROOT'] = str(Path(__file__).parent/'upstream')
    result['OPENLEARN_VISUAL_NODE_PACKAGE'] = str(Path(__file__).parent/'package.json')
    result['OPENLEARN_VISUAL_API_ORIGIN'] = 'http://127.0.0.1:' + os.getenv('PORT','8000')
    result['LANGSMITH_TRACING'] = 'false'
    result['COPILOTKIT_TELEMETRY_DISABLED'] = 'true'
    return result


def wait_ready(port, process):
    client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError('Visual sidecar exited during startup')
        try:
            with client.open(f'http://127.0.0.1:{port}/health',timeout=2) as response:
                if response.status==200:return
        except OSError:pass
        time.sleep(.5)
    raise RuntimeError('Visual sidecar readiness deadline exceeded')


def main():
    children=[]
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        env=sidecar_environment()
        commands=[([os.getenv('OPENLEARN_VISUAL_PYTHON','/opt/visual-agent/bin/python'),str(Path(__file__).parent/'agent.py')],8123),
                  (['node',str(Path(__file__).parent/'runtime.mjs')],8130)]
        for command,port in commands:
            child=subprocess.Popen(command,cwd=ROOT,env=env);children.append(child);wait_ready(port,child)
        api_env=dict(os.environ);api_env.setdefault('OPENLEARN_WORKER_MODE','embedded')
        hosted=os.getenv('AI_TUTOR_ENV') in {'production','deployed'}
        command=([sys.executable,'-m','backend.app.hosted_runtime',os.getenv('OPENLEARN_VISUAL_HOSTED_API_ROLE','api-free')]
                 if hosted else [sys.executable,'-m','uvicorn','backend.app.main:app','--host','0.0.0.0','--port',os.getenv('PORT','8000')])
        api=subprocess.Popen(command,cwd=ROOT,env=api_env)
        children.append(api)
        while not stopped:
            for name,child in zip(('visual graph','visual runtime','API'),children):
                if child.poll() is not None:
                    raise RuntimeError(f'{name} exited with code {child.returncode}')
            time.sleep(.5)
    finally:
        for child in reversed(children):
            if child.poll() is None:child.terminate()
        deadline=time.monotonic()+20
        for child in reversed(children):
            try:child.wait(timeout=max(.1,deadline-time.monotonic()))
            except subprocess.TimeoutExpired:child.kill()


if __name__=='__main__':main()
