# voronoi_mosaic
画像の局所的な色のばらつきをもとに、ボロノイ分割の母点を逐次的に追加して描画していくスクリプト。

CLIで使用することを想定しており、引数として以下の指定を受け付ける。

positional arguments:
-  input_path            入力画像パス
-  seeds_per_region      1領域から追加する母点数
-  output_path           出力画像パス

options:
-  -h, --help            show this help message and exit
-  --max-seeds MAX_SEEDS
                        総母点数の上限 (default: 64)
-  --gif                 各ステップを GIF 保存する
-  --gif-path GIF_PATH   GIF の出力先 (default: output_path と同名の .gif)
-  --frame-duration FRAME_DURATION
                        GIF フレーム間隔[ms] (default: 180)
-  --no-boundary         境界線を描かない
-  --min-seed-distance MIN_SEED_DISTANCE
                        新規母点の最小間隔[pixel] (default: 4.0)
