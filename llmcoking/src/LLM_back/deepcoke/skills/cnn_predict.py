"""
CNN 焦炭质量预测 — 基于煤样 6 维特征预测 CRI / CSR
输入: [Mad, Ad, Vdaf, St.d, G, Y]
输出: [CRI, CSR]
"""
import os
import logging
import numpy as np

logger = logging.getLogger("deepcoke.cnn_predict")

# ── 模型路径 ────────────────────────────────────────────────────
_MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models")
_MODEL_FILE = os.path.join(_MODEL_DIR, "(2026_3_15).4.779379.h5")

# ── 懒加载模型 ──────────────────────────────────────────────────
_model = None


def _load_model():
    global _model
    if _model is not None:
        return _model
    try:
        import tensorflow as tf
        tf.get_logger().setLevel("ERROR")
        _model = tf.keras.models.load_model(_MODEL_FILE)
        logger.info("CNN 模型加载成功")
    except Exception as e:
        logger.error(f"CNN 模型加载失败: {e}")
        _model = None
    return _model


# ── t-SNE 坐标映射（训练阶段固定） ─────────────────────────────
_TSNE_COORDS = np.array([
    [-2.2956204, 11.983552],
    [8.972184, 7.842322],
    [1.8764849, -4.529769],
    [-12.906775, 3.3454704],
    [-2.1228542, -47.829395],
    [-25.717352, 12.619746],
])

_x_coord = _TSNE_COORDS[:, 0]
_y_coord = _TSNE_COORDS[:, 1]
_x_min, _y_min = _x_coord.min(), _y_coord.min()
_x_max, _y_max = _x_coord.max(), _y_coord.max()

_x_pixel = np.round(1 + 8 * ((_x_coord - _x_min) / (_x_max - _x_min))).astype(int)
_y_pixel = np.round(1 + 8 * ((_y_coord - _y_min) / (_y_max - _y_min))).astype(int)

# ── 归一化参数（推理 notebook 中固定的 max/min） ────────────────
_DATA_MAX = np.array([0.930982, 0.803183, 0.952556, 0.075975, 0.928571, 0.727382], dtype=np.float32)
_DATA_MIN = np.array([0.000000, 0.108040, 0.383712, 0.000287, 0.128571, 0.093170], dtype=np.float32)

# 输入特征顺序
FEATURE_NAMES = ["coal_mad", "coal_ad", "coal_vdaf", "coal_std", "G", "Y"]
FEATURE_LABELS = ["水分Mad", "灰分Ad", "挥发分Vdaf", "硫分St,d", "粘结指数G", "胶质层Y"]


def _normalize(sample: np.ndarray) -> np.ndarray:
    """归一化：和推理 notebook 一致，直接用 data_max/data_min。"""
    # 推�� notebook 直接用这组参数对原始值归一化
    return (sample.astype(np.float32) - _DATA_MIN) / (_DATA_MAX - _DATA_MIN)


def _to_image(sample_norm: np.ndarray) -> np.ndarray:
    """将归一化的 6 维向量映射到 9x9 热力图再转为 64x64 RGB 图像。"""
    import cv2
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    grid = np.zeros((9, 9))
    for k, (px, py) in enumerate(zip(_x_pixel, _y_pixel)):
        if k < len(sample_norm):
            grid[py - 1][px - 1] = sample_norm[k]

    fig = plt.figure(figsize=(5, 5))
    sns.heatmap(grid, center=0, vmin=0, vmax=1, cbar=False,
                xticklabels=False, yticklabels=False)
    plt.tick_params(left=False, bottom=False)
    plt.subplots_adjust(top=1, bottom=0, right=1, left=0, hspace=0, wspace=0)
    plt.margins(0, 0)

    fig.canvas.draw()
    # 兼容新旧版本 matplotlib
    if hasattr(fig.canvas, 'tostring_rgb'):
        buf = fig.canvas.tostring_rgb()
    else:
        buf = fig.canvas.buffer_rgba()
    img = np.frombuffer(buf, dtype=np.uint8)
    w, h = fig.canvas.get_width_height()
    if len(img) == w * h * 4:
        img = img.reshape(h, w, 4)[:, :, :3]  # RGBA -> RGB
    else:
        img = img.reshape(h, w, 3)
    plt.close(fig)

    img = cv2.flip(img, 0)
    img = cv2.resize(img, (64, 64))
    img = img.astype("float32") / 255.0
    return img


def predict_cri_csr(mad: float, ad: float, vdaf: float, std: float,
                    g: float, y: float) -> dict:
    """
    用 CNN 预测单条煤样的 CRI 和 CSR。
    返回: {"CRI": float, "CSR": float} 或 {"error": str}
    """
    model = _load_model()
    if model is None:
        return {"error": "CNN 模型未加载，请检查 tensorflow 和模型文件"}

    sample = np.array([mad, ad, vdaf, std, g, y])
    sample_norm = _normalize(sample)
    img = _to_image(sample_norm)
    img_batch = np.expand_dims(img, axis=0)

    pred = model.predict(img_batch, verbose=0)
    cri, csr = float(pred[0][0]), float(pred[0][1])

    return {"CRI": round(cri, 2), "CSR": round(csr, 2)}


def predict_from_coal_dict(coal: dict) -> dict:
    """从煤样字典中提取特征并预测。"""
    missing = []
    vals = []
    for key in FEATURE_NAMES:
        v = coal.get(key)
        if v is None:
            missing.append(key)
            vals.append(0.0)
        else:
            vals.append(float(v))
    if missing:
        return {"error": f"缺少特征: {', '.join(missing)}"}
    return predict_cri_csr(*vals)


def predict_batch(coal_list: list[dict]) -> list[dict]:
    """批量预测，每条煤样返回带预测值的字典。"""
    results = []
    for coal in coal_list:
        name = coal.get("coal_name", "?")
        pred = predict_from_coal_dict(coal)
        pred["coal_name"] = name
        results.append(pred)
    return results
