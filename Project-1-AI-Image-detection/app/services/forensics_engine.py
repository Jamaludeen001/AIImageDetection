import logging
from PIL import Image
from PIL.ExifTags import TAGS

logger = logging.getLogger(__name__)

class EnterpriseImageForensicsEngine:
    def __init__(self, custom_signatures=None):
        #STRICT BLACKLIST: Only manual text editors and AI generators
        self.signatures = custom_signatures or [
            # Desktop Manual Editors
            'adobe photoshop', 'photoshop', 'lightroom', 'gimp', 'affinity photo', 
            'corel', 'paint.net', 'capture one', 'photopea',
            
            # Mobile Manual Text/Image Editors
            'picsart', 'snapseed', 'photoroom', 'epik', 'canva',
            
            # AI Generators & Frameworks
            'midjourney', 'dall-e', 'openai', 'stable diffusion', 'automatic1111', 
            'comfyui', 'fooocus', 'invokeai', 'flux', 'leonardo', 'ideogram', 
            'firefly', 'stability ai'
        ]

    def _check_metadata(self, pil_img, file_path: str) -> list:
        flags = []
        try:
            exif_data = pil_img.getexif() if hasattr(pil_img, 'getexif') else None
            
            if exif_data:
                for tag_id, value in exif_data.items():
                    tag_name = TAGS.get(tag_id, tag_id)
                    val_str = str(value).lower()
                    
                    # Only check the most common metadata fields where software is stored
                    if tag_name in ['Software', 'HostComputer', 'ImageDescription', 'Artist']:
                        if any(sig in val_str for sig in self.signatures):
                            flags.append(f"Metadata hit [{tag_name}]: {value}")

        except Exception as e:
            logger.error(f"Error parsing metadata for {file_path}: {e}")
            
        return flags

    def analyze_image(self, file_path: str) -> dict:
        report = {
            "file_path": file_path,
            "is_suspicious": False,
            "is_edited": False,
            "risk_score": 0.0,
            "flags": [],
            "metrics": {}
        }

        try:
            pil_img = Image.open(file_path)
            meta_flags = self._check_metadata(pil_img, file_path)
            
            if meta_flags:
                report["flags"].extend(meta_flags)
                report["risk_score"] = 0.35
                report["is_suspicious"] = True
                report["is_edited"] = True
            else:
                report["risk_score"] = 0.0
                report["is_suspicious"] = False
                report["is_edited"] = False

        except Exception as e:
            logger.error(f"Critical execution error: {e}")
            return {"error": str(e)}

        return report
