#!/bin/bash

set -e

cargo build --release

SOURCE="target/release/paperless_receipts"

DEST="../paperless_receipts.bin"

mv "$SOURCE" "$DEST"

echo "Done."
