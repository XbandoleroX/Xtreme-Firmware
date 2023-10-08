#!/usr/bin/env python
from PIL import Image, ImageOps
import heatshrink2
import pathlib
import shutil
import struct
import typing
import time
import re
import io
import os

# TODO: Create new entities for each actor
# TODO: Delegate the logic to the new entities
# TODO: Clean code smells (intense pedantry, shutgun surgery, etc)
# TODO: Desing a simple API to expose in the __name__ == "__main__" 
# TODO: Desing a simple API to expose in the __name__ == "__main__" 
class AssetPacker:
    def __init__(self) -> None:
        self.bm_extension = ".bm"
        self.bmx_extension = ".bmx"
        self.meta_str = "meta.txt"
        self.str_frame_rate = "frame_rate"

    def _with_io_bytes(self, img) -> bytes:
        if not isinstance(img, Image.Image):
            img = Image.open(img)

        with io.BytesIO() as output:
            img = img.convert("1")
            img = ImageOps.invert(img)
            img.save(output, format="XBM")
            xbm = output.getvalue()
        return xbm

    def _get_data_from_xbm(self, file) -> bytes:
        data = file.read().strip().replace("\n", "").replace(" ", "").split("=")[1][:-1]
        data_str = data[1:-1].replace(",", " ").replace("0x", "")
        data_bin = bytearray.fromhex(data_str)
        return data_bin

    def _get_data_encoded_from_xbm(self, data_bin) -> bytes:
        data_encoded_str = heatshrink2.compress(data_bin, window_sz2=8, lookahead_sz2=4)
        data_enc = bytearray(data_encoded_str)
        data_enc = bytearray([len(data_enc) & 0xFF, len(data_enc) >> 8]) + data_enc
        return data_enc

    def _encode_from_xbm(self, xbm) -> bytes:
        f = io.StringIO(xbm.decode().strip())
        data_bin = self._get_data_from_xbm(f)
        data_enc = self._get_data_encoded_from_xbm(data_bin)

        return [data_bin, data_enc]

    def _return_value_from_convert_bm(self, data_enc, data_bin) -> bytes:
        size_data_encoded = len(data_enc) + 2
        size_data_bin = len(data_bin) + 1

        if size_data_encoded < size_data_bin:
            return b"\x01\x00" + data_enc
        else:
            return b"\x00" + data_bin

    def _convert_bm(self, img: "Image.Image | pathlib.Path") -> bytes:
        xbm = self._with_io_bytes(img)
        data_bin, data_enc = self._encode_from_xbm(xbm) # let obviuos code show it self for later refactor
        return self._return_value_from_convert_bm(data_bin, data_enc)

    def _convert_bmx(self, img: "Image.Image | pathlib.Path") -> bytes:
        if not isinstance(img, Image.Image): img = Image.open(img)

        data = struct.pack("<II", *img.size)
        data += self._convert_bm(img)
        return data

    def _write_bytes_to_frame(self, dst, frame):
        bytes_to_write = self._convert_bm(frame)
        dst_bm = dst / frame.with_suffix(self.bm_extension).name
        dst_bm.write_bytes(bytes_to_write)

    def _copy_meta(self, src, dst):
        src_meta = src / self.meta_str
        dest_meta = dst / self.meta_str
        shutil.copyfile(src_meta, dest_meta)

    def _pack_anim(self, src: pathlib.Path, dst: pathlib.Path):
        src_meta = src / self.meta_str
        if not (src_meta).is_file(): return

        dst.mkdir(parents=True, exist_ok=True)
        for frame in src.iterdir():
            if not frame.is_file(): continue
            if frame.name == self.meta_str:
                self._copy_meta(src, dst)
                continue
            elif frame.name.startswith("frame_"):
                self._write_bytes_to_frame(dst, frame)

    def _pack_icon_animated(self, src: pathlib.Path, dst: pathlib.Path):
        if not (src / self.str_frame_rate).is_file():
            return
        dst.mkdir(parents=True, exist_ok=True)
        frame_count = 0
        frame_rate = None
        size = None
        for frame in src.iterdir():
            if not frame.is_file(): continue
            if frame.name == self.str_frame_rate:
                frame_rate = int((src / self.str_frame_rate).read_text())
                continue
            elif frame.name.startswith("frame_"):
                frame_count += 1
                if not size:
                    size = Image.open(frame).size
                (dst / frame.with_suffix(self.bm_extension).name).write_bytes(self._convert_bm(frame))
        (dst / "meta").write_bytes(struct.pack("<IIII", *size, frame_rate, frame_count))

    def _pack_icon_static(self, src: pathlib.Path, dst: pathlib.Path):
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.with_suffix(self.bmx_extension).write_bytes(self._convert_bmx(src))

    def begin(self, input: "str | pathlib.Path", output: "str | pathlib.Path", logger: typing.Callable):
        input = pathlib.Path(input)
        output = pathlib.Path(output)
        anims_str = "Anims"
        anims_manifest = "Anims/manifest.txt"
        icons_str = "Icons"
        # TODO: Encapsulate this logic
        for source in input.iterdir():
            if source == output or not source.is_dir(): continue

            logger(f"Pack: custom user pack '{source.name}'")
            packed = output / source.name
            if packed.exists():
                try:
                    shutil.rmtree(packed, ignore_errors=True) if packed.is_dir() else packed.unlink()
                except Exception:
                    pass

            full_path_anums_manifest = source / anims_manifest
            # TODO: Encapsulate this logic
            if (full_path_anums_manifest).exists():
                (packed / anims_str).mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / anims_manifest, packed / anims_manifest)
                manifest = (full_path_anums_manifest).read_bytes()
                for anim in re.finditer(rb"Name: (.*)", manifest):
                    anim = (
                        anim.group(1)
                        .decode()
                        .replace("\\", "/")
                        .replace("/", os.sep)
                        .replace("\r", "\n")
                        .strip()
                    )
                    logger(f"Compile: anim for pack '{source.name}': {anim}")
                    source_anims = source / anims_str / anim
                    packed_anims = packed / anims_str / anim
                    self._pack_anim(source_anims, packed_anims)
            # TODO: Reduce depth
            src_icons_path = source / icons_str
            if (src_icons_path).is_dir():
                for icons in (src_icons_path).iterdir():
                    if not icons.is_dir(): continue
                    for icon in icons.iterdir():
                        p = icon, packed / icons_str / icons.name / icon.name
                        if icon.is_dir():
                            logger(f"Compile: icon for pack '{source.name}': {icons.name}/{icon.name}")
                            self._pack_icon_animated(icon, p)
                        elif icon.is_file():
                            logger(f"Compile: icon for pack '{source.name}': {icons.name}/{icon.name}")
                            self._pack_icon_static(icon, p)


    def get_parent_directory(self, file) -> pathlib.Path:
        return pathlib.Path(file).absolute().parent


if __name__ == "__main__":
    ap = AssetPacker()
    input(
        "This will look through all the subfolders next to this file and try to pack them\n"
        "The resulting asset packs will be saved to 'asset_packs' in this folder\n"
        "Press [Enter] if you wish to continue"
    )
    print()

    here = ap.get_parent_directory(__file__)
    asset_pack_directory = here / "asset_packs"

    start_time = time.perf_counter()

    ap.begin(here, asset_pack_directory, logger=print)

    end_time = time.perf_counter()
    result_time = round(end_time - start_time, 2)

    print(f"\nFinished in {result_time}s\n" "Press [Enter] to exit")

