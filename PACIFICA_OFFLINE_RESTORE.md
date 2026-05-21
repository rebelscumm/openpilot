# Pacifica C2 Offline Restore

This repository is a self-contained snapshot of the comma two Pacifica setup.

## Included sources

- Openpilot/jvePilot root: `platyase/jvepilot`, branch `jvePilot-c2-release`, commit `2ab4983c9c6f577718ca9258647e20a683ee2244`.
- White panda firmware source: `offline_sources/panda-xps_wp_chrysler_basic`, from `xps-genesis/panda`, branch `xps_wp_chrysler_basic`, commit `0ce09fe7498a4fbd17bee8ea8968a6abef52f6e3`.
- C2 NEOS installer source: `offline_sources/c2-neos-alt-fix-install`, from `ophwug/c2-neos-alt-fix-install`, based on commit `1f0c8f3871ea3f02fbbfd8b86f53611a3020f4b5` with local modifications made during this install.

## Device settings used

- `launch_env.sh` is set for NEOS `20`.
- `steer.checkMinimum` should be set to `false` in `/data/op_params.json` on the comma.
- `panda/python/config.py` points `DEFAULT_FW_FN` at `/data/panda-xps-wp-basic/board/obj/panda.bin`, so `pandad` flashes the xps Chrysler basic white-panda firmware when the panda signature does not match.

## White panda firmware build

On the comma, copy or extract `offline_sources/panda-xps_wp_chrysler_basic` to:

```sh
/data/panda-xps-wp-basic
```

Then build:

```sh
cd /data/panda-xps-wp-basic/board
mkdir -p obj
make clean
make bin
sha1sum obj/panda.bin
```

Expected firmware hash from the working install:

```text
f8e2afcd58987a49b5a75a9f83d8312c0fd72a4b  obj/panda.bin
```

## Notes

The C2 shell wrappers must use LF line endings. If installing from Windows, normalize shell/Python scripts before launching on the comma.
