import json
import os
import numpy as np
from typing import Tuple, List, Optional
from shapely.geometry import Point, Polygon
import structlog

try:
    import cv2
except ImportError:
    cv2 = None

logger = structlog.get_logger()

class ZoneMapper:
    """
    Maps camera frame pixel coordinates to named store zones using homography projection
    or fallback passthrough mapping.
    """
    def __init__(self, store_layout_path: str):
        self.store_layout_path = store_layout_path
        self.homography = {}  # camera_id -> homography matrix
        self.zones = {}       # zone_id -> Polygon
        self.sku_mapping = {} # zone_id -> sku_zone
        
        layout = None
        
        # Try loading store_layout.json
        if os.path.exists(store_layout_path):
            try:
                with open(store_layout_path, "r", encoding="utf-8") as f:
                    layout = json.load(f)
                logger.info("Successfully loaded store layout configuration", path=store_layout_path)
            except Exception as e:
                logger.critical("Failed to parse store layout JSON, building fallback synthetic layout", 
                                path=store_layout_path, error=str(e))
        else:
            logger.critical("Store layout file does not exist, building fallback synthetic layout", 
                            path=store_layout_path)

        # Fallback to synthetic layout if missing or failed to parse
        if layout is None:
            layout = self._create_synthetic_layout()
            
        self.store_id = layout.get("store_id", "STORE_SYNTHETIC")
        
        # 1. Parse homography configurations per camera
        cameras = layout.get("cameras", {})
        for cam_id, config in cameras.items():
            src_pts = config.get("homography_src_points")
            dst_pts = config.get("homography_dst_points")
            
            if cv2 is not None and src_pts and dst_pts and len(src_pts) == 4 and len(dst_pts) == 4:
                src_arr = np.array(src_pts, dtype=np.float32)
                dst_arr = np.array(dst_pts, dtype=np.float32)
                self.homography[cam_id] = cv2.getPerspectiveTransform(src_arr, dst_arr)
            else:
                # Log warning if homography parameters are missing or cv2 is unavailable
                logger.warn("No homography configured or cv2 is missing. Operating in PASSTHROUGH mode for camera", 
                            camera_id=cam_id)
                
        # 2. Parse zones and build Shapely Polygon objects
        zones_list = layout.get("zones", [])
        for zone in zones_list:
            zone_id = zone.get("zone_id")
            polygon_coords = zone.get("polygon")
            sku = zone.get("sku_zone")
            
            if zone_id and polygon_coords and len(polygon_coords) >= 3:
                self.zones[zone_id] = Polygon(polygon_coords)
                if sku:
                    self.sku_mapping[zone_id] = sku

    def _create_synthetic_layout(self) -> dict:
        """
        Creates a fallback layout partitioning a 1920x1080 frame into four quadrants.
        """
        # Quadrants mapping:
        # Top-left (ENTRY_AREA): [0,0] to [960,540]
        # Top-right (MAIN_FLOOR): [960,0] to [1920,540]
        # Bottom-left (BILLING): [0,540] to [960,1080]
        # Bottom-right (EXIT_AREA): [960,540] to [1920,1080]
        return {
            "store_id": "STORE_FALLBACK_1920X1080",
            "cameras": {},  # Defaults to passthrough mode
            "zones": [
                {
                    "zone_id": "ENTRY_AREA",
                    "polygon": [[0, 0], [960, 0], [960, 540], [0, 540]]
                },
                {
                    "zone_id": "MAIN_FLOOR",
                    "polygon": [[960, 0], [1920, 0], [1920, 540], [960, 540]],
                    "sku_zone": "GENERIC_GOODS"
                },
                {
                    "zone_id": "BILLING",
                    "polygon": [[0, 540], [960, 540], [960, 1080], [0, 1080]]
                },
                {
                    "zone_id": "EXIT_AREA",
                    "polygon": [[960, 540], [1920, 540], [1920, 1080], [960, 1080]]
                }
            ]
        }

    def get_zone(self, foot_point: Tuple[float, float], camera_id: str) -> Optional[str]:
        """
        Maps a frame foot_point coordinate to a named store zone.
        """
        if cv2 is not None and camera_id in self.homography:
            # Map point using homography matrix
            pt_in = np.array([[[foot_point[0], foot_point[1]]]], dtype=np.float32)
            pt_out = cv2.perspectiveTransform(pt_in, self.homography[camera_id])
            map_point = Point(pt_out[0][0][0], pt_out[0][0][1])
        else:
            # Fallback: direct mapping in passthrough mode
            map_point = Point(foot_point[0], foot_point[1])
            
        for zone_id, polygon in self.zones.items():
            if polygon.contains(map_point):
                return zone_id
                
        return None

    def is_entry_zone(self, zone_id: Optional[str]) -> bool:
        """
        Returns true if the zone_id matches entry/entrance keywords.
        """
        return zone_id is not None and ("ENTRY" in zone_id.upper() or "ENTRANCE" in zone_id.upper())

    def is_billing_zone(self, zone_id: Optional[str]) -> bool:
        """
        Returns true if the zone_id matches billing keywords.
        """
        return zone_id is not None and ("BILLING" in zone_id.upper() or "CASH" in zone_id.upper())

    def get_zone_sku(self, zone_id: str) -> Optional[str]:
        """
        Returns the sku_zone associated with a zone_id.
        """
        return self.sku_mapping.get(zone_id)

    def get_all_zone_ids(self) -> List[str]:
        """
        Returns list of all zone_ids registered in layout.
        """
        return list(self.zones.keys())
