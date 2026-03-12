"""
条码扫描最简测试
================
用法：
  python barcode_test.py          # 打开摄像头，按 S 保存当前帧并尝试解码，按 Q 退出
  python barcode_test.py image.png # 直接解码图片文件

会把摄像头截图保存为 barcode_frame.png，方便发给别人看。
"""

import cv2
import sys
import numpy as np

# ── 检查 pyzbar ──
try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    print("✓ pyzbar 已安装")
except ImportError:
    print("✗ pyzbar 未安装！运行: pip install pyzbar")
    sys.exit(1)

def try_decode(img_bgr, label="原图"):
    """用多种预处理尝试解码，返回结果列表"""
    results = []
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    methods = {
        "原图灰度":        gray,
        "直方图均衡":      cv2.equalizeHist(gray),
        "高斯模糊+均衡":   cv2.equalizeHist(cv2.GaussianBlur(gray, (3, 3), 0)),
        "自适应阈值":      cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                  cv2.THRESH_BINARY, 31, 10),
        "OTSU二值化":      cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        "锐化":           cv2.filter2D(gray, -1, np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]])),
    }

    # 多尺度
    scales = [1.0, 1.5, 2.0, 0.5]

    for scale in scales:
        for name, processed in methods.items():
            if scale != 1.0:
                h, w = processed.shape
                processed = cv2.resize(processed, (int(w * scale), int(h * scale)),
                                       interpolation=cv2.INTER_LINEAR)
                tag = f"{name} @{scale}x"
            else:
                tag = name

            try:
                decoded = pyzbar_decode(processed)
            except Exception as e:
                decoded = []

            for d in decoded:
                code = d.data.decode("utf-8", errors="replace")
                results.append({
                    "method": tag,
                    "type":   d.type,
                    "data":   code,
                    "rect":   (d.rect.left, d.rect.top, d.rect.width, d.rect.height),
                })

    # 去重
    seen = set()
    unique = []
    for r in results:
        key = (r["type"], r["data"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def decode_file(path):
    """解码图片文件"""
    img = cv2.imread(path)
    if img is None:
        print(f"✗ 无法读取图片: {path}")
        return
    print(f"\n图片: {path}  ({img.shape[1]}×{img.shape[0]})")
    print("-" * 50)

    results = try_decode(img)
    if results:
        print(f"✓ 找到 {len(results)} 个条码:")
        for r in results:
            print(f"  [{r['type']}] {r['data']}  (方法: {r['method']})")
    else:
        print("✗ 未检测到任何条码")
        print("  可能原因:")
        print("  1. 条码不在画面中 / 太小")
        print("  2. 对焦模糊")
        print("  3. 反光 / 光线不足")
        print("  4. 条码类型不支持 (pyzbar 支持: EAN, UPC, Code128, QR 等)")

    # 保存标注图
    for r in results:
        x, y, w, h = r["rect"]
        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(img, r["data"], (x, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    out = path.rsplit(".", 1)[0] + "_result.png"
    cv2.imwrite(out, img)
    print(f"\n标注图已保存: {out}")


def camera_mode():
    """摄像头实时模式"""
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("✗ 无法打开摄像头")
        return

    # 尝试设置较高分辨率（有些摄像头默认 640x480 太低）
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    # 关闭自动对焦可能有助于固定焦距
    # cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    # cap.set(cv2.CAP_PROP_FOCUS, 50)  # 手动焦距

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"摄像头分辨率: {actual_w}×{actual_h}")
    print("操作: S=保存截图并解码  Q=退出  F=切换自动对焦")
    print()

    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        # 实时尝试解码（每5帧一次，减少卡顿）
        display = frame.copy()
        if frame_count % 5 == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            try:
                decoded = pyzbar_decode(gray)
            except:
                decoded = []
            for d in decoded:
                pts = d.polygon
                if pts:
                    pts_arr = np.array([(p.x, p.y) for p in pts], np.int32)
                    cv2.polylines(display, [pts_arr], True, (0, 255, 0), 3)
                code = d.data.decode("utf-8", errors="replace")
                r = d.rect
                cv2.putText(display, f"{d.type}: {code}",
                            (r.left, r.top - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                print(f"  实时检测: [{d.type}] {code}")

        cv2.imshow("Barcode Test - S:save Q:quit", display)
        frame_count += 1

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            fname = "barcode_frame.png"
            cv2.imwrite(fname, frame)
            print(f"\n已保存: {fname}")
            decode_file(fname)
            print()
        elif key == ord('f'):
            # 切换自动对焦
            af = cap.get(cv2.CAP_PROP_AUTOFOCUS)
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 0 if af else 1)
            print(f"自动对焦: {'关' if af else '开'}")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        decode_file(sys.argv[1])
    else:
        camera_mode()