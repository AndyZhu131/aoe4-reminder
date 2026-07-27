from aoe4.cli import main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        import sys

        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
