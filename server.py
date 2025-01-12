from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
from zhipuai import ZhipuAI
import os
import logging
import json
import time
from datetime import datetime, timedelta
from collections import deque
import threading

# 设置更详细的日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# 修改 CORS 设置，允许所有来源
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# 配置API密钥
API_KEY = os.getenv('API_KEY', "171991b2c95145a78b2e4807e098d7d2.me7koT1vDiusM7mV")
client = ZhipuAI(api_key=API_KEY)

# 设置模型名称和图片尺寸为常量
MODEL_NAME = "cogview-3-flash"
MODEL_NAME_IMAGE = "cogview-3-flash"
MODEL_NAME_VIDEO = "cogvideox-flash"
IMAGE_SIZE = "768x1344"  # 使用字符串格式的尺寸

# 添加请求限制
class RateLimiter:
    def __init__(self, max_requests=1, time_window=60):  # 默认1分钟1个请求
        self.max_requests = max_requests
        self.time_window = time_window  # 时间窗口（秒）
        self.requests = deque()
        self.lock = threading.Lock()

    def can_make_request(self):
        now = datetime.now()
        with self.lock:
            # 移除过期的请求记录
            while self.requests and self.requests[0] < now - timedelta(seconds=self.time_window):
                self.requests.popleft()
            
            # 检查是否超过限制
            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                return True
            return False

# 创建限流器实例
video_rate_limiter = RateLimiter(max_requests=1, time_window=60)

@app.route('/test-connection', methods=['GET'])
def test_connection():
    try:
        logger.info("开始测试API连接")
        if not API_KEY:
            raise ValueError("API密钥未设置")
            
        test_client = ZhipuAI(api_key=API_KEY)
        
        # 使用 cogview-3-flash 模型，添加size参数
        response = test_client.images.generations(
            model=MODEL_NAME,
            prompt="test image",
            size=IMAGE_SIZE
        )
        
        logger.info(f"API测试成功: {response}")
        return jsonify({
            'status': 'success',
            'message': 'API连接正常，智谱AI服务可用',
            'details': str(response)
        })
    except Exception as e:
        error_msg = f"API测试失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return jsonify({
            'status': 'error',
            'message': error_msg,
            'type': type(e).__name__
        }), 500

@app.route('/generate-image', methods=['POST'])
def generate_image():
    try:
        logger.info("收到生成图片请求")
        data = request.get_json(force=True)
        prompt = data.get('prompt', '')
        
        if not prompt:
            logger.warning("未提供提示词")
            return jsonify({'error': '请提供提示词'}), 400
        
        logger.info(f"正在生成图片，提示词: {prompt}")
        
        # 尝试生成图片，使用size参数
        try:
            response = client.images.generations(
                model=MODEL_NAME,
                prompt=prompt,
                size=IMAGE_SIZE
            )
            
            if hasattr(response, 'data') and len(response.data) > 0:
                image_url = response.data[0].url
                logger.info(f"图片生成成功: {image_url}")
                return jsonify({'url': image_url})
            else:
                raise ValueError("API返回数据格式不正确")
                
        except Exception as api_error:
            logger.error(f"API调用错误: {str(api_error)}")
            return jsonify({'error': f"图片生成失败: {str(api_error)}"}), 500
    
    except Exception as e:
        error_msg = f"请求处理错误: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return jsonify({'error': error_msg}), 500

@app.route('/generate-video', methods=['POST'])
def generate_video():
    try:
        if not video_rate_limiter.can_make_request():
            return jsonify({
                'error': '请求过于频繁，请等待一分钟后再试'
            }), 429

        logger.info("收到生成视频请求")
        data = request.get_json(force=True)
        image_url = data.get('image_url', '')
        prompt = data.get('prompt', '让画面动起来')
        
        if not image_url:
            logger.warning("未提供图片URL")
            return jsonify({'error': '请提供图片URL'}), 400
        
        logger.info(f"正在生成视频，图片URL: {image_url}")
        
        try:
            response = client.videos.generations(
                model=MODEL_NAME_VIDEO,
                image_url=image_url,
                prompt=prompt,
                quality="quality",
                with_audio=True,
                size="1080x1920",
                duration=10,
                fps=30
            )
            
            logger.info(f"视频生成任务已提交: {response}")
            
            if hasattr(response, 'id'):
                return jsonify({
                    'status': 'processing',
                    'task_id': response.id,
                    'request_id': getattr(response, 'request_id', None)
                })
            else:
                raise ValueError("API响应中未包含任务ID")
                
        except Exception as api_error:
            error_msg = str(api_error)
            logger.error(f"API调用错误: {error_msg}")
            return jsonify({'error': f"视频生成失败: {error_msg}"}), 500
    
    except Exception as e:
        error_msg = f"请求处理错误: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return jsonify({'error': error_msg}), 500

@app.route('/check-video-status/<task_id>', methods=['GET'])
def check_video_status(task_id):
    try:
        logger.info(f"检查视频任务状态: {task_id}")
        
        # 使用 retrieve_videos_result 方法获取状态
        response = client.videos.retrieve_videos_result(id=task_id)
        
        logger.info(f"获取到任务状态: {response}")
        
        # 直接从对象获取属性
        task_status = getattr(response, 'task_status', None)
        if task_status:
            if task_status == "SUCCESS":
                video_result = getattr(response, 'video_result', None)
                if video_result and len(video_result) > 0:
                    return jsonify({
                        'status': 'completed',
                        'video_url': video_result[0].url,
                        'cover_image_url': video_result[0].cover_image_url
                    })
                else:
                    raise ValueError("视频结果格式不正确")
            elif task_status == "FAIL":
                return jsonify({
                    'status': 'failed',
                    'error': '视频生成失败'
                })
            else:  # PROCESSING 状态
                return jsonify({
                    'status': 'processing',
                    'task_id': getattr(response, 'id', task_id),
                    'request_id': getattr(response, 'request_id', None),
                    'model': getattr(response, 'model', None)
                })
        else:
            raise ValueError(f"无效的响应格式: {response}")
            
    except Exception as e:
        error_msg = f"检查视频状态失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return jsonify({
            'status': 'error',
            'error': error_msg
        }), 500

@app.route('/ping', methods=['GET'])
def ping():
    try:
        logger.info("收到ping请求")
        return jsonify({
            'status': 'success',
            'message': 'pong',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Ping失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/')
def home():
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"加载主页失败: {str(e)}")
        return str(e), 500

if __name__ == '__main__':
    app.run()
else:
    # 这是为了 Vercel 部署
    app = app 