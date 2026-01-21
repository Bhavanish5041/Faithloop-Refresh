import matlab.engine
import io

class MATLABTool:
    _instance = None
    _engine = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MATLABTool, cls).__new__(cls)
            print("--- [System]: Starting MATLAB Engine... ---")
            try:
                cls._engine = matlab.engine.start_matlab()
                print("--- [System]: MATLAB Engine Ready. ---")
            except Exception as e:
                print(f"--- [System]: MATLAB Start Failed: {e} ---")
                cls._engine = None
        return cls._instance

    def run(self, code: str) -> str:
        if self._engine is None: return "Error: MATLAB Engine is not running."
        try:
            out = io.StringIO()
            err = io.StringIO()
            self._engine.eval(code, nargout=0, stdout=out, stderr=err)
            return out.getvalue().strip() or err.getvalue().strip() or "[Done]"
        except Exception as e:
            return f"Execution Error: {str(e)}"
