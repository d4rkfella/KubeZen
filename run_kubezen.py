import os
import sys
import logging
import textual

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))


if __name__ == "__main__":
    if '--tui' in sys.argv:
        from KubeZen.app import KubeZenTuiApp
        from KubeZen.config import AppConfig
        config = AppConfig.get_instance()
        KubeZenTuiApp(config=config).run()
    else:
        from KubeZen.main import main
        main()
