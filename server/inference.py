import numpy as np
from PIL import Image
import io
import time

class YOLODetector:
    def __init__(self, model_path, labels_path, conf_threshold=0.4, iou_threshold=0.45, flip_image=False):
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.flip_image = flip_image  # Set True if camera is mounted upside-down
        
        with open(labels_path, 'r') as f:
            self.labels = [line.strip() for line in f.readlines() if line.strip()]
        
        try:
            import tflite_runtime.interpreter as tflite
            self.interpreter = tflite.Interpreter(model_path=model_path, num_threads=4)
        except ImportError:
            try:
                from ai_edge_litert import interpreter as ai_interpreter
                self.interpreter = ai_interpreter.Interpreter(model_path=model_path, num_threads=4)
            except ImportError:
                import tensorflow as tf
                self.interpreter = tf.lite.Interpreter(model_path=model_path, num_threads=4)
        
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        self.input_shape = self.input_details[0]['shape']
        self.input_dtype = self.input_details[0]['dtype']
        # Detect tensor layout: NCHW (1,3,H,W) vs NHWC (1,H,W,3).
        # Ultralytics TFLite exports vary between the two.
        if len(self.input_shape) == 4 and self.input_shape[1] == 3 and self.input_shape[3] != 3:
            self.channels_first = True
            self.input_h = int(self.input_shape[2])
            self.input_w = int(self.input_shape[3])
        else:
            self.channels_first = False
            self.input_h = int(self.input_shape[1])
            self.input_w = int(self.input_shape[2])
        
        # Check for quantization
        self.is_quantized = self.input_dtype == np.uint8 or self.input_dtype == np.int8
        
        print(f"[Model] Input shape: {self.input_shape}")
        print(f"[Model] Input dtype: {self.input_dtype}")
        print(f"[Model] Quantized: {self.is_quantized}")
        print(f"[Model] Output shape: {self.output_details[0]['shape']}")
        print(f"[Model] Output dtype: {self.output_details[0]['dtype']}")
        print(f"[Model] Labels ({len(self.labels)}): {self.labels}")

    def preprocess(self, image_input):
        if isinstance(image_input, bytes):
            img = Image.open(io.BytesIO(image_input)).convert('RGB')
        elif isinstance(image_input, str):
            img = Image.open(image_input).convert('RGB')
        else:
            img = image_input.convert('RGB')
        
        if self.flip_image:
            img = img.rotate(180, expand=True)  # 180° rotation, fixes upside-down camera
        
        original_size = img.size  # (width, height)
        img = img.resize((self.input_w, self.input_h))
        
        if self.is_quantized:
            # INT8/UINT8 model: keep as uint8 [0, 255]
            img_array = np.array(img, dtype=np.uint8)
        else:
            # FLOAT32 model: normalize to [0.0, 1.0]
            img_array = np.array(img, dtype=np.float32) / 255.0
        
        if self.channels_first:
            img_array = np.transpose(img_array, (2, 0, 1))  # HWC -> CHW

        img_array = np.expand_dims(img_array, axis=0)
        return img_array, original_size

    def run_inference(self, img_array):
        self.interpreter.set_tensor(self.input_details[0]['index'], img_array)
        self.interpreter.invoke()
        output = self.interpreter.get_tensor(self.output_details[0]['index'])
        return output

    def postprocess(self, output, original_size):
        output = output[0]
        
        # Dequantize output if needed
        out_details = self.output_details[0]
        if out_details['dtype'] == np.uint8 or out_details['dtype'] == np.int8:
            quant_params = out_details.get('quantization_parameters', {})
            scales = quant_params.get('scales', [])
            zero_points = quant_params.get('zero_points', [])
            if len(scales) > 0:
                output = (output.astype(np.float32) - zero_points[0]) * scales[0]
        
        # YOLOv8 output: [num_classes+4, num_boxes] -> transpose to [num_boxes, num_classes+4]
        if output.shape[0] == len(self.labels) + 4:
            output = output.T
        
        num_classes = len(self.labels)
        boxes_raw = output[:, :4]   # cx, cy, w, h in MODEL PIXEL space (0 to input_w/input_h)
        scores_raw = output[:, 4:4+num_classes]
        
        class_ids = np.argmax(scores_raw, axis=1)
        confidences = np.max(scores_raw, axis=1)
        
        mask = confidences > self.conf_threshold
        boxes_raw = boxes_raw[mask]
        confidences = confidences[mask]
        class_ids = class_ids[mask]
        
        if len(boxes_raw) == 0:
            return []
        
        # Auto-detect coordinate format:
        # If max values > 1.0, coordinates are in pixel space (0 to input_w)
        # If max values <= 1.0, coordinates are normalized (0 to 1)
        max_coord = np.max(boxes_raw[:, :2])  # check cx, cy values
        
        if max_coord > 1.0:
            # Pixel space: scale from model input size to original image size
            scale_x = original_size[0] / self.input_w
            scale_y = original_size[1] / self.input_h
        else:
            # Normalized: scale directly to original image size
            scale_x = original_size[0]
            scale_y = original_size[1]
        
        # Convert from cxcywh to x1y1x2y2
        cx = boxes_raw[:, 0] * scale_x
        cy = boxes_raw[:, 1] * scale_y
        w = boxes_raw[:, 2] * scale_x
        h = boxes_raw[:, 3] * scale_y
        
        x1 = cx - w / 2
        y1 = cy - h / 2
        x2 = cx + w / 2
        y2 = cy + h / 2
        
        # Clip to image bounds
        orig_w, orig_h = original_size
        x1 = np.clip(x1, 0, orig_w)
        y1 = np.clip(y1, 0, orig_h)
        x2 = np.clip(x2, 0, orig_w)
        y2 = np.clip(y2, 0, orig_h)
        
        boxes = np.stack([x1, y1, x2, y2], axis=1)
        
        results = []
        indices = self.nms(boxes, confidences, self.iou_threshold)
        for i in indices:
            results.append({
                'class': self.labels[class_ids[i]] if class_ids[i] < len(self.labels) else f'class_{class_ids[i]}',
                'confidence': float(confidences[i]),
                'box': [float(boxes[i][0]), float(boxes[i][1]),
                        float(boxes[i][2]), float(boxes[i][3])]
            })
        return results

    def nms(self, boxes, scores, iou_threshold):
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]
        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h
            iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
            inds = np.where(iou <= iou_threshold)[0]
            order = order[inds + 1]
        return keep

    def detect(self, image_input):
        img_array, original_size = self.preprocess(image_input)
        t0 = time.time()
        output = self.run_inference(img_array)
        inference_time = time.time() - t0
        detections = self.postprocess(output, original_size)
        return detections, inference_time, original_size
