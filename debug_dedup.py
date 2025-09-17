#!/usr/bin/env python3

import os
import re
from youspotter.utils.path_template import to_path_regex
from youspotter.utils.matching import normalize_text

# Test the deduplication logic
def test_deduplication():
    # Create test directory structure like user's example
    test_host = "./test_music"
    os.makedirs(f"{test_host}/The Magic Wanderer/The Magic Inns & Villages", exist_ok=True)

    # Create test file
    test_file = f"{test_host}/The Magic Wanderer/The Magic Inns & Villages/The Magic Wanderer - Castle Carousal.mp3"
    with open(test_file, 'w') as f:
        f.write("test")

    # Also create the .webp file like in user's example
    webp_file = f"{test_host}/The Magic Wanderer/The Magic Inns & Villages/The Magic Wanderer - Castle Carousal.webp"
    with open(webp_file, 'w') as f:
        f.write("test")

    # Test the path template regex
    tmpl = '{artist}/{album}/{artist} - {title}.{ext}'
    fmt = 'mp3'

    print(f"Template: {tmpl}")
    print(f"Format: {fmt}")

    try:
        pattern = re.compile(to_path_regex(tmpl))
        print(f"Regex pattern: {pattern.pattern}")

        existing_pairs = set()

        for root, _dirs, files in os.walk(test_host):
            for fn in files:
                print(f"Checking file: {fn}")
                if not fn.lower().endswith(f'.{fmt}'):
                    print(f"  Skipping non-{fmt} file: {fn}")
                    continue

                rel = os.path.relpath(os.path.join(root, fn), test_host)
                rel = rel.replace('\\', '/')  # normalize
                print(f"  Relative path: {rel}")

                m = pattern.match(rel)
                if not m:
                    print(f"  No regex match for: {rel}")
                    continue

                gd = m.groupdict()
                print(f"  Regex groups: {gd}")

                a = normalize_text(gd.get('artist') or '')
                t = normalize_text(gd.get('title') or '')
                print(f"  Normalized artist: '{a}'")
                print(f"  Normalized title: '{t}'")

                if a and t:
                    existing_pairs.add((a, t))
                    print(f"  Added to existing: ({a}, {t})")

        print(f"\nExisting pairs found: {existing_pairs}")

        # Test track that should be deduplicated
        test_track = {
            'artist': 'The Magic Wanderer',
            'title': 'Castle Carousal'
        }

        track_key = (normalize_text(test_track.get('artist','')), normalize_text(test_track.get('title','')))
        print(f"\nTest track key: {track_key}")
        print(f"Should be deduplicated: {track_key in existing_pairs}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    # Cleanup
    import shutil
    shutil.rmtree(test_host, ignore_errors=True)

if __name__ == "__main__":
    test_deduplication()