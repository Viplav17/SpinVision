from picamera2 import Picamera2
import requests
import time
import os
import sys
import base64
from config import GEMINI_API_KEY, MESHY_API_KEY

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
MESHY_URL = "https://api.meshy.ai/openapi/v2"

def take_picture(filename):
    try:
        os.makedirs("images", exist_ok=True)
        path = os.path.join("images", filename)
        
        cam = Picamera2()
        config = cam.create_still_configuration(main={"size": (1280, 720)})
        
        # Try to set crop/zoom if scaler is available
        try:
            sensor_size = cam.sensor_resolution
            zoom_factor = 1.5
            
            crop_width = int(sensor_size[0] / zoom_factor)
            crop_height = int(sensor_size[1] / zoom_factor)
            crop_x = (sensor_size[0] - crop_width) // 2
            crop_y = (sensor_size[1] - crop_height) // 2
            
            if "scaler" in config:
                config["scaler"]["crop"] = (crop_x, crop_y, crop_width, crop_height)
            else:
                print("Note: Scaler not available, using full sensor")
        except Exception as e:
            print(f"Note: Could not set crop/zoom: {e}")
        
        cam.configure(config)
        cam.start()
        time.sleep(2)
        
        cam.capture_file(path)
        print(f"Saved: {path}")
        
        cam.stop()
        cam.close()
        return path
    except Exception as e:
        print(f"Error: {e}")
        return None

def encode_image(image_path):
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')

def send_to_gemini(image_path):
    print("\n" + "=" * 60)
    print("Sending image to Gemini API...")
    print("=" * 60)
    
    image_data = encode_image(image_path)
    
    parts = [
        {
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": image_data
            }
        },
        {
            "text": "Analyze this image and provide a highly detailed description of the object. Ignore the wooden platform or base completely. Focus exclusively on the object itself. Describe: 1) Object type and category (what is it?), 2) Exact dimensions and proportions (relative size, width, height, depth), 3) Shape details (geometric forms, curves, angles, edges, contours), 4) Surface characteristics (smooth, rough, textured, glossy, matte), 5) Colors and materials (exact colors, patterns, material type like metal, plastic, ceramic, etc.), 6) Depth and volume (3D structure, thickness, hollow or solid), 7) Fluidity and movement (if applicable, how it flows or moves), 8) Fine details (engravings, markings, textures, small features), 9) Structural elements (joints, connections, separate parts), 10) Overall geometry (symmetry, asymmetry, organic or geometric forms). Be extremely specific and detailed about every visible aspect of the object."
        }
    ]
    
    payload = {
        "contents": [{
            "parts": parts
        }]
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY
    }
    
    try:
        response = requests.post(GEMINI_URL, headers=headers, json=payload)
        if response.status_code == 200:
            result = response.json()
            text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
            print("Gemini response received!")
            print("\nFull Gemini prompt:")
            print(text)
            print(f"\nPrompt length: {len(text)} characters")
            return text
        else:
            print(f"Gemini API error: {response.status_code}")
            print(f"Error: {response.text}")
            return None
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return None

def send_to_meshy(gemini_response, output_dir="3d_models"):
    print("\n" + "=" * 60)
    print("Sending to Meshy.ai for 3D model generation...")
    print("=" * 60)
    
    os.makedirs(output_dir, exist_ok=True)
    
    prompt = gemini_response[:600]
    print(f"\nTruncated prompt for Meshy (600 chars max): {prompt}")
    print(f"Truncated prompt length: {len(prompt)} characters")
    
    url = f"{MESHY_URL}/text-to-3d"
    headers = {
        "Authorization": f"Bearer {MESHY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "mode": "preview",
        "prompt": prompt
    }
    
    try:
        print("Uploading prompt to Meshy.ai...")
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code in [200, 201, 202]:
            result = response.json()
            task_id = result.get('result')
            print(f"Upload successful! Task ID: {task_id}")
            print(f"Status code: {response.status_code} (Accepted for processing)")
            
            print("\nWaiting for 3D model generation...")
            print("This may take a few minutes...")
            
            max_wait = 600
            wait_time = 0
            check_interval = 5
            
            while wait_time < max_wait:
                time.sleep(check_interval)
                wait_time += check_interval
                
                status_url = f"{MESHY_URL}/text-to-3d/{task_id}"
                status_response = requests.get(status_url, headers=headers)
                
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    status = status_data.get('status', 'unknown')
                    progress = status_data.get('progress', 0)
                    model_urls = status_data.get('model_urls', {})
                    
                    print(f"Status: {status} | Progress: {progress}% | Time: {wait_time}s")
                    
                    model_url = None
                    if model_urls:
                        model_url = model_urls.get('glb') or model_urls.get('obj') or model_urls.get('fbx')
                    
                    if status == 'SUCCEEDED' or (model_url and progress >= 99):
                        if progress >= 98 and status != 'SUCCEEDED':
                            print("\nModel appears ready (99%+ progress), checking for download URLs...")
                        
                        if not model_url:
                            model_url = status_data.get('thumbnail_url')
                        
                        if model_url:
                            output_path = os.path.join(output_dir, "model_3d.glb")
                            
                            if not model_url.startswith('http'):
                                model_url = f"https://api.meshy.ai{model_url}"
                            
                            print(f"\n3D model generation complete!")
                            print(f"Downloading 3D model to: {output_path}...")
                            download_response = requests.get(model_url, stream=True)
                            
                            if download_response.status_code == 200:
                                with open(output_path, 'wb') as f:
                                    for chunk in download_response.iter_content(chunk_size=8192):
                                        f.write(chunk)
                                print(f"✓ Success! 3D model saved to: {output_path}")
                                return True
                            else:
                                print(f"Download failed: {download_response.status_code}")
                                print(f"Response: {download_response.text[:200]}")
                                if wait_time < max_wait - 30:
                                    print("Retrying in 30 seconds...")
                                    continue
                                return False
                        else:
                            if progress >= 99:
                                print("Progress is 99% but model URL not available yet. Waiting...")
                                continue
                            print("Error: Model URL not found in response")
                            if wait_time < max_wait - 30:
                                continue
                            return False
                    
                    elif status == 'FAILED':
                        print("\nError: 3D model generation failed")
                        error_msg = status_data.get('task_error', {}).get('message', 'Unknown error')
                        print(f"Error message: {error_msg}")
                        print(f"Full response: {status_data}")
                        return False
                    
                    elif status == 'CANCELED':
                        print("\nError: 3D model generation was canceled")
                        return False
                else:
                    print(f"Status check failed: {status_response.status_code}")
                    print(f"Response: {status_response.text[:200]}")
                    if wait_time < max_wait - 30:
                        continue
            
            print(f"\nTimeout: Model generation took longer than {max_wait} seconds")
            print("Checking one final time if model is available...")
            
            final_check = requests.get(f"{MESHY_URL}/text-to-3d/{task_id}", headers=headers)
            if final_check.status_code == 200:
                final_data = final_check.json()
                model_urls = final_data.get('model_urls', {})
                model_url = model_urls.get('glb') or model_urls.get('obj') or model_urls.get('fbx')
                if model_url:
                    output_path = os.path.join(output_dir, "model_3d.glb")
                    if not model_url.startswith('http'):
                        model_url = f"https://api.meshy.ai{model_url}"
                    print(f"Found model URL! Downloading to: {output_path}...")
                    download_response = requests.get(model_url, stream=True)
                    if download_response.status_code == 200:
                        with open(output_path, 'wb') as f:
                            for chunk in download_response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        print(f"✓ Success! 3D model saved to: {output_path}")
                        return True
            
            return False
        else:
            print(f"Meshy.ai upload failed: {response.status_code}")
            print(f"Error: {response.text}")
            return False
    except Exception as e:
        print(f"Error calling Meshy.ai: {e}")
        return False

def main():
    folder = "images"
    
    try:
        os.makedirs(folder, exist_ok=True)
        
        print("=" * 60)
        print("Starting 3D Scan Process")
        print("=" * 60)
        print("Taking one picture for testing...")
        
        name = "scan_image.jpg"
        img_path = take_picture(name)
        
        if not img_path:
            print("Error: Failed to capture image!")
            return
        
        print(f"\nDone! Image saved to: {img_path}")
        
        gemini_response = send_to_gemini(img_path)
        if not gemini_response:
            print("Error: Failed to get response from Gemini")
            return
        
        success = send_to_meshy(gemini_response)
        
        if success:
            print("\n" + "=" * 60)
            print("Complete! 3D model generated successfully!")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("3D model generation failed")
            print("=" * 60)
        
    except KeyboardInterrupt:
        print("\nStopped by user")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
