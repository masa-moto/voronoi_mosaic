from __future__ import annotations

from pathlib import Path
import argparse

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree
from tqdm import tqdm 


def build_pixel_coords(width: int, height: int) -> np.ndarray:
    """各画素の座標を (x, y) の shape=(H*W, 2) で返す。"""
    yy, xx = np.mgrid[0:height, 0:width]
    coords = np.column_stack([xx.ravel(), yy.ravel()]).astype(np.float32)
    return coords


def assign_labels(pixel_coords: np.ndarray, seeds: np.ndarray) -> np.ndarray:
    """各画素を最近傍の seed に割り当てる。"""
    tree = cKDTree(seeds)
    _, labels = tree.query(pixel_coords, k=1)
    return labels.astype(np.int32)


def render_mean_color_image(
    img: np.ndarray,
    labels: np.ndarray,
    n_labels: int,
    draw_boundaries: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """
    各 Voronoi 領域をその平均色で塗った画像を返す。
    同時に各領域の再構成誤差（SSE）も返す。
    """
    height, width, _ = img.shape
    flat_img = img.reshape(-1, 3).astype(np.float32)

    out = np.zeros_like(flat_img, dtype=np.float32)
    errors = np.zeros(n_labels, dtype=np.float64)

    for label in range(n_labels):
        idx = np.where(labels == label)[0]
        if idx.size == 0:
            continue

        region = flat_img[idx]
        mean_rgb = region.mean(axis=0)
        out[idx] = mean_rgb

        diff = region - mean_rgb
        errors[label] = np.sum(diff * diff)

    out_img = np.clip(out.reshape(height, width, 3), 0, 255).astype(np.uint8)

    if draw_boundaries:
        labels_2d = labels.reshape(height, width)
        boundary = np.zeros((height, width), dtype=bool)
        boundary[:, 1:] |= labels_2d[:, 1:] != labels_2d[:, :-1]
        boundary[1:, :] |= labels_2d[1:, :] != labels_2d[:-1, :]

        out_img = out_img.copy()
        out_img[boundary] = 0  # 境界を黒で描く

    return out_img, errors


def select_new_seeds_from_region(
    img: np.ndarray,
    labels_2d: np.ndarray,
    target_label: int,
    n_new_seeds: int,
    existing_seeds: np.ndarray,
    min_seed_distance: float = 4.0,
) -> list[tuple[float, float]]:
    """
    指定領域から新しい seed を選ぶ。

    規則:
    - 領域の RGB 平均から最も遠い画素を優先
    - 同率っぽい場合の補助として、領域の (x, y) 平均から遠いものを優先
    - 既存 seed と近すぎる点は避ける
    """
    ys, xs = np.nonzero(labels_2d == target_label)
    if xs.size == 0:
        return []

    coords = np.column_stack([xs, ys]).astype(np.float32)       # (N, 2), x-y順
    colors = img[ys, xs].astype(np.float32)                     # (N, 3)

    mean_rgb = colors.mean(axis=0)
    mean_xy = coords.mean(axis=0)

    color_d2 = np.sum((colors - mean_rgb) ** 2, axis=1)        # RGB平均との差
    spatial_d2 = np.sum((coords - mean_xy) ** 2, axis=1)       # 領域重心からの距離

    # 第1キー: color_d2, 第2キー: spatial_d2 を大きい順
    order = np.lexsort((spatial_d2, color_d2))[::-1]

    selected: list[tuple[float, float]] = []
    min_d2 = float(min_seed_distance ** 2)

    for idx in order:
        p = coords[idx]  # [x, y]

        # 既存 seeds と近すぎるものを避ける
        if existing_seeds.size > 0:
            d2_existing = np.min(np.sum((existing_seeds - p) ** 2, axis=1))
            if d2_existing < min_d2:
                continue

        # 同じ iteration 内で選んだ新規 seeds 同士も近すぎるものを避ける
        if selected:
            sel_arr = np.asarray(selected, dtype=np.float32)
            d2_selected = np.min(np.sum((sel_arr - p) ** 2, axis=1))
            if d2_selected < min_d2:
                continue

        selected.append((float(p[0]), float(p[1])))

        if len(selected) >= n_new_seeds:
            break

    return selected


def greedy_voronoi_segmentation(
    input_path: str,
    seeds_per_region: int,
    output_path: str,
    max_seeds: int = 64,
    save_gif: bool = False,
    gif_path: str | None = None,
    frame_duration_ms: int = 180,
    draw_boundaries: bool = True,
    min_seed_distance: float = 4.0,
) -> np.ndarray:
    """
    誤差最大の Voronoi 領域から seed を追加していく greedy segmentation。

    Parameters
    ----------
    input_path : str
        入力画像パス
    seeds_per_region : int
        1 回の更新で、選ばれた 1 領域から追加する母点数
    output_path : str
        出力画像パス
    max_seeds : int
        総母点数の上限
    save_gif : bool
        各 step を保存して GIF を出すか
    gif_path : str | None
        GIF 出力先。None のとき output_path と同名で .gif
    """
    image = Image.open(input_path).convert("RGB")
    img = np.asarray(image).astype(np.float32)
    height, width, _ = img.shape

    pixel_coords = build_pixel_coords(width, height)

    # 初期 seed: 画像中心に 1 点
    seeds = np.array([[width / 2.0, height / 2.0]], dtype=np.float32)

    frames: list[Image.Image] = []
    pbar = tqdm(
        total=max_seeds - len(seeds),
        desc="Adding Voronoi seeds",
        unit="seed",
        dynamic_ncols=True,
        ncols = 50
    )

    while len(seeds) < max_seeds:
        labels = assign_labels(pixel_coords, seeds)
        labels_2d = labels.reshape(height, width)

        rendered, errors = render_mean_color_image(
            img,
            labels,
            n_labels=len(seeds),
            draw_boundaries=draw_boundaries,
        )

        if save_gif:
            frames.append(Image.fromarray(rendered.copy()))

        target_label = int(np.argmax(errors))

        new_seeds = select_new_seeds_from_region(
            img=img,
            labels_2d=labels_2d,
            target_label=target_label,
            n_new_seeds=seeds_per_region,
            existing_seeds=seeds,
            min_seed_distance=min_seed_distance,
        )

        if not new_seeds:
            break

        remaining = max_seeds - len(seeds)
        new_seeds = new_seeds[:remaining]

        if not new_seeds:
            break

        seeds = np.vstack([seeds, np.asarray(new_seeds, dtype=np.float32)])

        pbar.update(len(new_seeds))
        pbar.set_postfix(
            {
                "seeds": len(seeds),
                "max_error": f"{float(np.max(errors)):.2e}",
            }
        )

    pbar.close()
    # 最終結果を再描画
    labels = assign_labels(pixel_coords, seeds)
    rendered, _ = render_mean_color_image(
        img,
        labels,
        n_labels=len(seeds),
        draw_boundaries=draw_boundaries,
    )

    Image.fromarray(rendered).save(output_path)

    if save_gif and frames:
        final_frame = Image.fromarray(rendered.copy())
        frames.append(final_frame)

        if gif_path is None:
            gif_path = str(Path(output_path).with_suffix(".gif"))

        frames[0].save(
            gif_path,
            save_all=True,
            append_images=frames[1:],
            duration=frame_duration_ms,
            loop=0,
        )

    return seeds


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path", type=str, help="入力画像パス")
    parser.add_argument("seeds_per_region", type=int, help="1領域から追加する母点数")
    parser.add_argument("output_path", type=str, help="出力画像パス")

    parser.add_argument(
        "--max-seeds",
        type=int,
        default=64,
        help="総母点数の上限 (default: 64)",
    )
    parser.add_argument(
        "--gif",
        action="store_true",
        help="各ステップを GIF 保存する",
    )
    parser.add_argument(
        "--gif-path",
        type=str,
        default=None,
        help="GIF の出力先 (default: output_path と同名の .gif)",
    )
    parser.add_argument(
        "--frame-duration",
        type=int,
        default=180,
        help="GIF フレーム間隔[ms] (default: 180)",
    )
    parser.add_argument(
        "--no-boundary",
        action="store_true",
        help="境界線を描かない",
    )
    parser.add_argument(
        "--min-seed-distance",
        type=float,
        default=4.0,
        help="新規母点の最小間隔[pixel] (default: 4.0)",
    )

    args = parser.parse_args()

    greedy_voronoi_segmentation(
        input_path=args.input_path,
        seeds_per_region=args.seeds_per_region,
        output_path=args.output_path,
        max_seeds=args.max_seeds,
        save_gif=args.gif,
        gif_path=args.gif_path,
        frame_duration_ms=args.frame_duration,
        draw_boundaries=not args.no_boundary,
        min_seed_distance=args.min_seed_distance,
    )
if __name__ == "__main__":
    main()
