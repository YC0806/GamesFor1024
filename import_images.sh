#!/bin/bash

set -euo pipefail

print_usage() {
    echo "Usage: $0 <image_directory>" >&2
}

if [[ $# -ne 1 ]]; then
    print_usage
    exit 1
fi

image_dir=$1

if [[ ! -d "$image_dir" ]]; then
    echo "Directory not found: $image_dir" >&2
    exit 1
fi

shopt -s nullglob
found_images=0

for image_path in "$image_dir"/*.tar; do
    found_images=1
    if docker load -i "$image_path"; then
        echo "Imported image: $(basename "$image_path")"
    else
        echo "Failed to import: $(basename "$image_path")" >&2
    fi
done

if [[ $found_images -eq 0 ]]; then
    echo "No .tar images found in $image_dir" >&2
fi
