"""
条码扫描改进方案
================
核心改动：
1. 摄像头分辨率从 320x240 提升到 1280x720（或摄像头最大值）
2. 条码扫描用高分辨率帧，UI预览仍用低分辨率
3. 增加超分辨率预处理
"""

# ═══════════════════════════════════════
#  方案 A：最小改动 — 修改你现有代码的摄像头线程
# ═══════════════════════════════════════

# ---------- 替换你的 camera_thread ----------
"""
关键：摄像头线程要用高分辨率采集，分两个队列输出：
  - cv_queue: 低分辨率帧给 UI 预览和水果识别
  - cv_hires_queue: 高分辨率帧给条码扫描
"""

CAMERA_PATCH = """
import queue, threading, cv2

cv_queue       = queue.Queue()          # 低分辨率，给 UI + 水果识别
cv_hires_queue = queue.Queue()          # 高分辨率，给条码扫描
CAM_W, CAM_H   = 320, 240              # UI 预览尺寸

def camera_thread():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("无法打开摄像头"); return

    # ★ 核心改动：请求高分辨率
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    # 有些摄像头需要手动关闭自动对焦才能近距离对焦
    # cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    # cap.set(cv2.CAP_PROP_FOCUS, 40)   # 0-255, 值越小越近焦

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"摄像头实际分辨率: {actual_w}x{actual_h}")

    while True:
        ret, frame = cap.read()
        if not ret: continue

        # 低分辨率给 UI
        small = cv2.resize(frame, (CAM_W, CAM_H))
        if cv_queue.qsize() >= 2: cv_queue.get()
        cv_queue.put(small)

        # 高分辨率给条码（只在条码模式时更新）
        if _bc_scan_active.is_set():
            if cv_hires_queue.qsize() >= 2: cv_hires_queue.get()
            cv_hires_queue.put(frame)

threading.Thread(target=camera_thread, daemon=True).start()
"""

# ---------- 替换你的 barcode_scan_thread ----------
BARCODE_PATCH = """
def barcode_scan_thread():
    last_code = ""
    while True:
        _bc_scan_active.wait()

        # ★ 用高分辨率帧
        if cv_hires_queue.empty():
            time.sleep(0.05); continue
        frame = list(cv_hires_queue.queue)[-1]

        if not PYZBAR_OK:
            time.sleep(0.1); continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        results = []
        # 多种预处理
        preprocessed = [
            gray,
            cv2.equalizeHist(gray),
            cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8)).apply(gray),
            cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        ]

        for proc in preprocessed:
            decoded = _suppress_stderr_decode(proc)
            if decoded:
                results = decoded
                break
            # 如果原尺寸不行，放大 1.5x 再试
            h, w = proc.shape
            big = cv2.resize(proc, (int(w*1.5), int(h*1.5)), interpolation=cv2.INTER_CUBIC)
            decoded = _suppress_stderr_decode(big)
            if decoded:
                results = decoded
                break

        if results:
            rects = []
            for bc in results:
                code = bc.data.decode("utf-8", errors="replace").strip()
                r = bc.rect
                rects.append((r.left, r.top, r.width, r.height))
                if code and code != last_code:
                    last_code = code
                    if barcode_raw_queue.full():
                        try: barcode_raw_queue.get_nowait()
                        except: pass
                    barcode_raw_queue.put((code, rects))
                    break
        else:
            last_code = ""

        time.sleep(0.08)

threading.Thread(target=barcode_scan_thread, daemon=True).start()
"""

print("=" * 60)
print("  条码扫描改进方案")
print("=" * 60)
print()
print("你的条码扫不到的原因:")
print("  ❌ 摄像头采集只有 320×240")
print("  ❌ 条码在画面中太小，黑白条纹只有 1-2px 宽")
print("  ❌ 对焦模糊，条纹粘连在一起")
print()
print("改进方法（从易到难）:")
print()
print("【1】提高分辨率（最重要！）")
print("   把 camera_thread 里 VideoCapture 设置为 1280x720")
print("   条码扫描用高分辨率帧，UI预览缩小显示")
print()
print("【2】对焦距离")  
print("   条码要占画面的 1/3 以上")
print("   手拿近一些，确保条码清晰")
print()
print("【3】光线")
print("   避免反光（你的图有塑料膜反光）")
print("   保证条码区域光线均匀")
print()
print("具体代码改动见文件中的 CAMERA_PATCH 和 BARCODE_PATCH")


# ═══════════════════════════════════════
#  方案 B：快速验证 — 独立测试脚本
# ═══════════════════════════════════════
if __name__ == "__main__":
    import sys
    
    print("\n" + "=" * 60)
    print("  快速验证: 高分辨率摄像头条码扫描")
    print("=" * 60)
    
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
    except ImportError:
        print("需要: pip install pyzbar")
        sys.exit(1)
    
    import cv2, numpy as np
    
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("无法打开摄像头")
        sys.exit(1)
    
    # 请求最高分辨率
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"分辨率: {w}x{h}")
    print("对准条码，按 S 截图解码，Q 退出")
    
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret: continue
        
        display = frame.copy()
        
        # 每 3 帧尝试解码
        if frame_count % 3 == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # 多种预处理尝试
            for proc in [
                gray,
                cv2.equalizeHist(gray),
                cv2.createCLAHE(clipLimit=3.0).apply(gray),
            ]:
                decoded = pyzbar_decode(proc)
                if decoded:
                    for d in decoded:
                        code = d.data.decode("utf-8", errors="replace")
                        print(f"  ✓ [{d.type}] {code}")
                        # 画框
                        pts = d.polygon
                        if pts:
                            arr = np.array([(p.x, p.y) for p in pts], np.int32)
                            cv2.polylines(display, [arr], True, (0, 255, 0), 3)
                        r = d.rect
                        cv2.putText(display, code, (r.left, r.top - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                    break
        
        # 缩小显示
        show = cv2.resize(display, (960, 540))
        cv2.imshow("Barcode Test (HD) - S:save Q:quit", show)
        frame_count += 1
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            cv2.imwrite("barcode_hd.png", frame)
            print(f"已保存 barcode_hd.png ({w}x{h})")
    
    cap.release()
    cv2.destroyAllWindows()