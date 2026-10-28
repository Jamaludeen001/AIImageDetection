import logging
from PIL import Image
from PIL.ExifTags import TAGS

logger = logging.getLogger(__name__)

class EnterpriseImageForensicsEngine:
    def __init__(self, custom_signatures=None):
        self.signatures = custom_signatures or [
            # Desktop Editors
            'adobe', 'photoshop', 'lightroom', 'gimp', 'affinity', 'pixelmator',
            'corel', 'paint.net', 'capture one', 'luminar', 'photopea',
            
            # Mobile & iOS Editors
            'canva', 'picsart', 'snapseed', 'facetune', 'vsco', 'pixlr', 'meitu',
            'photoroom', 'epik', 'hypic', 'remini', 'lightroom mobile', 'pixelmator mobile',
            'capcut', 'over', 'dazz cam',
            
            # AI Generators & Frameworks
            'firefly', 'stability', 'midjourney', 'dall-e', 'openai', 'stable diffusion',
            'automatic1111', 'comfyui', 'fooocus', 'invokeai', 'flux', 'leonardo', 'ideogram'
        ]

    def _check_metadata(self, pil_img, file_path: str) -> list:
        """Deep inspection of PNG text chunks, standard EXIF tags, and XMP XML packets."""
        flags = []
        try:
            # 1. Scan PNG Info Chunks & AI Generation Parameters
            if hasattr(pil_img, 'info') and pil_img.info:
                for key, value in pil_img.info.items():
                    val_str = str(value).lower()
                    if any(sig in val_str for sig in self.signatures) or key.lower() in ['parameters', 'workflow', 'prompt', 'generator']:
                        flags.append(f"Metadata hit in PNG info chunk [{key}]: {str(value)[:80]}...")

            # 2. Scan Standard EXIF Data
            exif_data = pil_img.getexif() if hasattr(pil_img, 'getexif') else None
            if exif_data:
                for tag_id, value in exif_data.items():
                    tag_name = TAGS.get(tag_id, tag_id)
                    val_str = str(value).lower()
                    if tag_name in ['Software', 'HostComputer', 'ImageDescription', 'Artist'] and any(sig in val_str for sig in self.signatures):
                        flags.append(f"EXIF tag hit [{tag_name}]: {value}")

            # 3. Scan XMP Metadata (XML packets embedded in image headers)
            xmp_data = pil_img.getxmp() if hasattr(pil_img, 'getxmp') else None
            if xmp_data:
                xmp_str = str(xmp_data).lower()
                for sig in self.signatures:
                    if sig in xmp_str:
                        flags.append(f"XMP Packet signature match found: '{sig}' detected in XML metadata.")
                        break

        except Exception as e:
            logger.error(f"Error parsing metadata for {file_path}: {e}")
            
        return flags

    def analyze_image(self, file_path: str) -> dict:
        """Runs the metadata forensic verification suite."""
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
            
            # Only run the metadata check
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