"""Uvicorn entrypoint that preserves Cerebro's safe logging configuration."""

import uvicorn


def main() -> None:
    uvicorn.run(
        "cerebro.main:app",
        host="0.0.0.0",
        port=8000,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config=None,
    )


if __name__ == "__main__":
    main()
