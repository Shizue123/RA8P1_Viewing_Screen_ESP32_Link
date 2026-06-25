from __future__ import annotations

import argparse
import json

from cloud.app.config import get_settings
from cloud.app.model_config import ModelSelectionRequest, update_model_selection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider")
    parser.add_argument("model")
    args = parser.parse_args()
    result = update_model_selection(
        get_settings(),
        ModelSelectionRequest(provider=args.provider, model=args.model),
    )
    print(json.dumps(result["active"], ensure_ascii=False))


if __name__ == "__main__":
    main()
