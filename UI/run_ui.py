"""通过绝对入口定位 UI。启动时不构造 SimulatedLIBS，不联网。"""
import sys

sys.dont_write_bytecode = True
for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8')


def main():
    from simlibs_ui.app import main as app_main
    return app_main()


if __name__ == '__main__':
    raise SystemExit(main())
