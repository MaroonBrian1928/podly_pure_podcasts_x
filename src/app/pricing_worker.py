"""Disposable LiteLLM pricing lookup; stdin model/tier pairs, stdout rate triples."""

import contextlib
import json
import sys


def main() -> None:
    models = json.load(sys.stdin)
    # SDK diagnostics must not corrupt the JSON IPC response.
    with contextlib.redirect_stdout(sys.stderr):
        import litellm  # noqa: F401 -- fail the helper if the SDK cannot load

        from app.llm_pricing import RATE_KEYS, rate_from_litellm

        rates = [
            [rate_from_litellm(name, key, tier) for key in RATE_KEYS]
            for name, tier in models
        ]
    json.dump(rates, sys.stdout)


if __name__ == "__main__":
    main()
