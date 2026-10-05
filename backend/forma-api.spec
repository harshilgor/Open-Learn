# PyInstaller specification for the local Forma API sidecar.
from pathlib import Path

root = Path(SPECPATH)
hidden = [
    "backend",
    "backend.app",
    "backend.app.main",
    "backend.app.assessment_generation",
    "backend.app.assessment_models",
    "backend.app.context_service",
    "backend.app.database",
    "backend.app.graph_generator",
    "backend.app.journey_service",
    "backend.app.learner_graph",
    "backend.app.learning_kernel",
    "backend.app.learning_policy",
    "backend.app.learning_routes",
    "backend.app.material_models",
    "backend.app.material_routes",
    "backend.app.material_service",
    "backend.app.material_worker",
    "backend.app.model_provider",
    "backend.app.models",
    "backend.app.policy_models",
    "backend.app.quiz_service",
    "backend.app.reading_format",
    "backend.app.session_models",
    "backend.app.state_models",
    "backend.app.state_routes",
    "backend.app.state_service",
    "backend.app.storage",
    "backend.app.workflow_store",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
]

a = Analysis(
    [str(root / "desktop_entry.py")],
    pathex=[str(root.parent)],
    hiddenimports=hidden,
    datas=[
        (str(root / "app" / "flashcards" / "skill.json"), "backend/app/flashcards"),
        (str(root / "app" / "flashcards" / "instructions.txt"), "backend/app/flashcards"),
        (str(root / "migrations"), "backend/migrations"),
        (str(root / "alembic.ini"), "backend"),
        (str(root / "app" / "browser_assistant" / "observer.js"), "backend/app/browser_assistant"),
        (str(root / "app" / "browser_assistant" / "adapters" / "canvas-read.js"), "backend/app/browser_assistant/adapters"),
        (str(root.parent / "canvas-extension"), "canvas-extension"),
    ],
    excludes=["tkinter", "pytest", "IPython", "matplotlib", "numpy", "PIL", "zmq", "pygame", "jedi", "parso"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="forma-api",
    # Keep a console subsystem so startup errors are visible when the sidecar is
    # launched manually. Electron starts it with windowsHide=true in production.
    console=True,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="forma-api",
)
