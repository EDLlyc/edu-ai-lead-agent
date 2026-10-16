import inspect

from app.application.services import execute_acquisition
from app.application.services.execute_acquisition import AcquisitionExecutor
from app.worker_main import run_worker  # noqa: F401  the real entry point still imports

source = inspect.getsource(execute_acquisition)
assert "acquisition_item_parse_skipped" in source
assert "no article page of this source could be read" in source
assert hasattr(AcquisitionExecutor, "execute_next")
print("acquisition_skip_ok")
