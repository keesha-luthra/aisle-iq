import uuid
import numpy as np
import torch
import torch.nn as nn
import torchvision.models as models
from typing import List, Tuple, Optional
from datetime import datetime
import structlog

try:
    import cv2
except ImportError:
    cv2 = None

# Try importing torchreid (optional)
try:
    import torchreid
    TORCHREID_AVAILABLE = True
except ImportError:
    TORCHREID_AVAILABLE = False

logger = structlog.get_logger()

class EmbeddingExtractor:
    """
    Extracts a 512-dimensional appearance embedding from a person crop.
    """
    def __init__(self, device: str = "cpu"):
        self.device = device
        self.active_backend = "resnet18"
        
        # 1. Attempt to load OSNet from torchreid
        if TORCHREID_AVAILABLE:
            try:
                # Ensure weights path exists or fallback
                weights_path = 'weights/osnet_x0_25.pth'
                self.extractor = torchreid.utils.FeatureExtractor(
                    model_name='osnet_x0_25',
                    model_path=weights_path,
                    device=device
                )
                self.active_backend = "torchreid"
                logger.info("EmbeddingExtractor initialized with OSNet (torchreid)", device=device)
                return
            except Exception as e:
                logger.warn("Failed to load torchreid model, falling back to resnet18", error=str(e))
                
        # 2. Fall back to ResNet-18
        try:
            # Try loading default ImageNet pretrained weights
            resnet = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
        except Exception:
            # If offline / default weights fails to download
            resnet = models.resnet18(weights=None)
            
        # Strip final FC layer to get 512-dim features
        self.extractor = nn.Sequential(*list(resnet.children())[:-1])
        self.extractor.eval()
        self.extractor.to(self.device)
        
        logger.info("EmbeddingExtractor initialized with ResNet-18 (torchvision)", device=self.device)

    def extract(self, frame: np.ndarray, bbox: tuple) -> np.ndarray:
        """
        Crops frame to bbox, resizes, normalizes, and extracts L2-normalized 512-dim embedding.
        """
        try:
            h, w, _ = frame.shape
            x1, y1, x2, y2 = [int(coord) for coord in bbox]
            # Clamp coordinates to frame boundaries
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                return np.zeros(512, dtype=np.float32)
                
            # Convert BGR to RGB (standard Re-ID input format)
            if cv2 is not None and len(crop.shape) == 3 and crop.shape[2] == 3:
                crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                # Resize to (128, 256) standard Re-ID dimensions
                crop_resized = cv2.resize(crop_rgb, (128, 256))
            else:
                crop_rgb = crop
                crop_resized = crop_rgb
                
            # Normalize with ImageNet mean/std
            crop_float = crop_resized.astype(np.float32) / 255.0
            mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
            std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
            crop_normalized = (crop_float - mean) / std
            
            # Convert to channels-first tensor shape: (3, H, W)
            crop_tensor = crop_normalized.transpose(2, 0, 1)
            tensor = torch.tensor(crop_tensor, dtype=torch.float32).unsqueeze(0).to(self.device)
            
            with torch.no_grad():
                if self.active_backend == "torchreid":
                    embedding_tensor = self.extractor(tensor)
                else:
                    embedding_tensor = self.extractor(tensor)
                    embedding_tensor = torch.flatten(embedding_tensor, 1)
                    
            embedding = embedding_tensor.cpu().numpy().flatten()
            
            # L2 Normalization
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            else:
                embedding = np.zeros(512, dtype=np.float32)
                
            return embedding.astype(np.float32)
            
        except Exception as e:
            logger.error("Embedding extraction failed", error=str(e))
            return np.zeros(512, dtype=np.float32)

class VisitorTracker:
    """
    Maps local (per-camera) track_ids to stable global visitor_ids.
    """
    def __init__(self, reid_threshold: float = 0.75, reentry_window_seconds: int = 300, device: str | None = None):
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            
        self.track_to_visitor = {}      # track_id -> visitor_id
        self.visitor_embeddings = {}    # visitor_id -> mean embedding
        self.visitor_last_seen = {}     # visitor_id -> datetime
        self.visitor_exit_times = {}    # visitor_id -> datetime
        
        self.embedding_extractor = EmbeddingExtractor(device=device)
        self.reid_threshold = reid_threshold
        self.reentry_window_seconds = reentry_window_seconds
        
        # Add gallery alias for compatibility with test assertions
        self.gallery = self.visitor_embeddings

    def get_visitor_id(self, track_id: int, frame: np.ndarray, bbox: tuple, 
                       camera_id: str = "CAM_GENERIC_01", frame_time: datetime | None = None) -> Tuple[str, bool]:
        """
        Resolves local track_id to a stable global visitor_id.
        Returns (visitor_id, is_reentry)
        """
        if frame_time is None:
            from datetime import timezone
            frame_time = datetime.now(timezone.utc)

        # If track is already mapped, return cached mapping
        if track_id in self.track_to_visitor:
            visitor_id = self.track_to_visitor[track_id]
            self.visitor_last_seen[visitor_id] = frame_time
            return (visitor_id, False)

        # Extract appearance embedding
        embedding = self.embedding_extractor.extract(frame, bbox)
        
        # Search all registered visitors for matches within target time window
        best_match_id = None
        best_similarity = 0.0
        
        for vid, emb in self.visitor_embeddings.items():
            if vid in self.visitor_exit_times:
                elapsed = abs((frame_time - self.visitor_exit_times[vid]).total_seconds())
                if elapsed <= self.reentry_window_seconds:
                    # cosine similarity (both are L2-normalized)
                    sim = float(np.dot(embedding, emb))
                    if sim > best_similarity:
                        best_similarity = sim
                        best_match_id = vid

        if best_match_id and best_similarity >= self.reid_threshold:
            # Re-entry matched!
            visitor_id = best_match_id
            self.track_to_visitor[track_id] = visitor_id
            self.visitor_exit_times.pop(visitor_id, None)
            
            # Update mean rolling embedding and re-normalize
            new_emb = 0.9 * self.visitor_embeddings[visitor_id] + 0.1 * embedding
            norm = np.linalg.norm(new_emb)
            self.visitor_embeddings[visitor_id] = new_emb / norm if norm > 0 else new_emb
            self.visitor_last_seen[visitor_id] = frame_time
            return (visitor_id, True)

        # Completely new visitor registration
        visitor_id = "VIS_" + uuid.uuid4().hex[:6]
        self.track_to_visitor[track_id] = visitor_id
        self.visitor_embeddings[visitor_id] = embedding
        self.visitor_last_seen[visitor_id] = frame_time
        return (visitor_id, False)

    def mark_exited(self, visitor_id: str, exit_time: datetime):
        """
        Records the exit time and cleans active track mappings.
        """
        self.visitor_exit_times[visitor_id] = exit_time
        stale_tracks = [t for t, v in self.track_to_visitor.items() if v == visitor_id]
        for t in stale_tracks:
            del self.track_to_visitor[t]

    def get_active_visitors(self) -> List[str]:
        """
        Returns list of active global visitor_ids.
        """
        return [vid for vid in self.visitor_embeddings if vid not in self.visitor_exit_times]

# Alias for compatibility with tests
ReIDTracker = VisitorTracker

