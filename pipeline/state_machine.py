import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, List
from dataclasses import dataclass

@dataclass
class VisitorState:
    visitor_id: str
    store_id: str
    is_staff: bool
    current_zone: Optional[str] = None
    previous_zone: Optional[str] = None
    zone_entry_time: Optional[datetime] = None
    last_dwell_emit_time: Optional[datetime] = None
    session_seq: int = 0
    entry_time: Optional[datetime] = None
    has_entered: bool = True
    has_exited: bool = False
    is_in_billing_queue: bool = False
    billing_queue_entry_time: Optional[datetime] = None
    last_seen_time: Optional[datetime] = None

class StateMachine:
    """
    State machine that processes camera-level tracking inputs and
    produces business-oriented events matching the StoreEvent schema.
    """
    def __init__(self, zone_mapper=None, staff_classifier=None, tracker=None,
                 zone_dwell_seconds: float = 30.0, queue_dwell_seconds: float = 5.0,
                 inactivity_timeout_seconds: float = 5.0):
        self.states = {}
        self.pending_events = []
        self.zone_mapper = zone_mapper
        self.staff_classifier = staff_classifier
        self.tracker = tracker
        self.zone_dwell_seconds = zone_dwell_seconds
        self.queue_dwell_seconds = queue_dwell_seconds
        self.inactivity_timeout_seconds = inactivity_timeout_seconds

    def update(self, visitor_id: str, zone_id: Optional[str], is_staff: bool, 
               confidence: float, store_id: str, camera_id: str, 
               frame_time: Optional[datetime] = None, is_reentry: bool = False,
               timestamp: Optional[datetime] = None, metadata: Optional[dict] = None) -> List[dict]:
        """
        Updates the visitor's state machine with a frame detection and returns triggered events.
        """
        actual_time = frame_time if frame_time is not None else timestamp
        if actual_time is None:
            actual_time = datetime.now(timezone.utc)
            
        self._handle_initial_state(visitor_id, zone_id, is_staff, confidence, store_id, camera_id, actual_time, is_reentry, metadata)
        
        state = self.states[visitor_id]
        state.is_staff = is_staff
        state.last_seen_time = actual_time

        is_entry_cam = "ENTRY" in camera_id.upper() or camera_id in ("CAM_03", "cam1", "entry 1", "entry 2")
        is_entry_z = self.zone_mapper.is_entry_zone(zone_id) if (self.zone_mapper and zone_id) else False
        if is_entry_cam or is_entry_z:
            state.has_entered = True

        self._handle_zone_transition(state, visitor_id, zone_id, is_staff, confidence, store_id, camera_id, actual_time, metadata)
        self._handle_zone_dwell(state, visitor_id, is_staff, confidence, store_id, camera_id, actual_time, metadata)

        return self.flush_pending()

    def _handle_initial_state(self, visitor_id: str, zone_id: Optional[str], is_staff: bool, confidence: float, store_id: str, camera_id: str, actual_time: datetime, is_reentry: bool, metadata: Optional[dict]):
        if visitor_id in self.states:
            return
            
        state = VisitorState(
            visitor_id=visitor_id,
            store_id=store_id,
            is_staff=is_staff,
            entry_time=actual_time,
            zone_entry_time=actual_time,
            last_dwell_emit_time=actual_time,
            last_seen_time=actual_time,
            has_entered=False
        )
        self.states[visitor_id] = state
        
        if is_reentry:
            self._emit("REENTRY", visitor_id, store_id, camera_id, zone_id, 0, is_staff, confidence, actual_time, metadata)
            state.has_entered = True
        else:
            is_entry_cam = "ENTRY" in camera_id.upper()
            is_entry_z = self.zone_mapper.is_entry_zone(zone_id) if (self.zone_mapper and zone_id) else False
            if is_entry_cam or is_entry_z:
                self._emit("ENTRY", visitor_id, store_id, camera_id, None, 0, is_staff, confidence, actual_time, metadata)
                state.has_entered = True

    def _handle_zone_transition(self, state: VisitorState, visitor_id: str, zone_id: Optional[str], is_staff: bool, confidence: float, store_id: str, camera_id: str, actual_time: datetime, metadata: Optional[dict]):
        if zone_id == state.current_zone:
            return

        if state.current_zone is not None:
            dwell_ms = int((actual_time - state.zone_entry_time).total_seconds() * 1000) if state.zone_entry_time else 0
            self._emit("ZONE_EXIT", visitor_id, store_id, camera_id, state.current_zone, dwell_ms, is_staff, confidence, actual_time, metadata)
            
        if zone_id is not None:
            self._emit("ZONE_ENTER", visitor_id, store_id, camera_id, zone_id, 0, is_staff, confidence, actual_time, metadata)
            state.zone_entry_time = actual_time
            state.last_dwell_emit_time = actual_time
            
            is_billing = self.zone_mapper.is_billing_zone(zone_id) if self.zone_mapper else False
            if is_billing:
                state.billing_queue_entry_time = actual_time
                
        state.previous_zone = state.current_zone
        state.current_zone = zone_id

    def _handle_zone_dwell(self, state: VisitorState, visitor_id: str, is_staff: bool, confidence: float, store_id: str, camera_id: str, actual_time: datetime, metadata: Optional[dict]):
        if state.current_zone is not None and state.last_dwell_emit_time is not None:
            elapsed = (actual_time - state.last_dwell_emit_time).total_seconds()
            if elapsed >= self.zone_dwell_seconds:
                self._emit("ZONE_DWELL", visitor_id, store_id, camera_id, state.current_zone, int(elapsed * 1000), is_staff, confidence, actual_time, metadata)
                state.last_dwell_emit_time = actual_time

    def update_empty(self, frame_time: datetime) -> List[dict]:
        """
        Processes a frame with no detections. Checks for visitor inactivity
        and forces exit events for visitors who haven't been seen for
        the inactivity timeout duration.
        """
        store_id = "STORE_GENERIC_01"
        if self.states:
            store_id = next(iter(self.states.values())).store_id
            
        self.handle_empty_period(frame_time, store_id)
        return self.flush_pending()

    def handle_empty_period(self, frame_time: datetime, store_id: str):
        """
        Called when a full frame has zero detections.
        For each state in self.states that has been seen but not updated in > 5 seconds:
          They have likely exited. Emit a synthetic EXIT event.
          Remove from states.
        """
        visitor_ids = list(self.states.keys())
        for visitor_id in visitor_ids:
            state = self.states[visitor_id]
            last_seen = state.last_seen_time or state.entry_time or frame_time
            if (frame_time - last_seen).total_seconds() > self.inactivity_timeout_seconds:
                events = self.handle_exit(
                    visitor_id=visitor_id,
                    camera_id="CAM_EMPTY_PERIOD",
                    frame_time=frame_time,
                    store_id=store_id
                )
                self.pending_events.extend(events)


    def handle_exit(self, visitor_id: str, camera_id: str, frame_time: datetime, 
                    store_id: str) -> List[dict]:
        """
        Forces an EXIT event for a visitor, clearing their state tracking.
        """
        if visitor_id not in self.states:
            return []
            
        state = self.states[visitor_id]
        
        # Calculate exit_time: backdate to last frame they were actually seen if possible
        exit_time = state.last_seen_time if state.last_seen_time else frame_time
        
        # 1. Exit current zone
        if state.current_zone:
            dwell_ms = 0
            if state.zone_entry_time:
                dwell_ms = int((exit_time - state.zone_entry_time).total_seconds() * 1000)
            self._emit(
                event_type="ZONE_EXIT",
                visitor_id=visitor_id,
                store_id=store_id,
                camera_id=camera_id,
                zone_id=state.current_zone,
                dwell_ms=dwell_ms,
                is_staff=state.is_staff,
                confidence=1.0,
                frame_time=exit_time
            )
            
        # 2. Emit global EXIT only if they have entered, AND (it's an entry camera/zone, or a final flush)
        is_entry_cam = "ENTRY" in camera_id.upper() or "EXIT" in camera_id.upper() or camera_id in ("CAM_03", "cam1", "entry 1", "entry 2")
        is_entry_z = self.zone_mapper.is_entry_zone(state.current_zone) if (self.zone_mapper and state.current_zone) else False
        is_final_flush = camera_id in ("CAM_EXIT", "CAM_EMPTY_PERIOD")
        
        if state.has_entered and (is_entry_cam or is_entry_z or is_final_flush):
            dwell_ms = 0
            if state.entry_time:
                dwell_ms = int((exit_time - state.entry_time).total_seconds() * 1000)
            self._emit(
                event_type="EXIT",
                visitor_id=visitor_id,
                store_id=store_id,
                camera_id=camera_id,
                zone_id=None,
                dwell_ms=dwell_ms,
                is_staff=state.is_staff,
                confidence=1.0,
                frame_time=exit_time
            )
        
        state.has_exited = True
        del self.states[visitor_id]
        return self.flush_pending()

    def handle_billing_queue_join(self, visitor_id: str, queue_depth: int, 
                                  camera_id: str, frame_time: datetime, 
                                  store_id: str) -> List[dict]:
        """
        Upgrades the pending ZONE_ENTER for BILLING to BILLING_QUEUE_JOIN in the queue buffer.
        """
        found = False
        for ev in self.pending_events:
            if ev["visitor_id"] == visitor_id and ev["event_type"] == "ZONE_ENTER":
                is_billing = self.zone_mapper.is_billing_zone(ev["zone_id"]) if self.zone_mapper else False
                if is_billing or (ev["zone_id"] and "BILLING" in ev["zone_id"].upper()):
                    ev["event_type"] = "BILLING_QUEUE_JOIN"
                    if "metadata" not in ev or ev["metadata"] is None:
                        ev["metadata"] = {}
                    ev["metadata"]["queue_depth"] = queue_depth
                    found = True
                    if visitor_id in self.states:
                        state = self.states[visitor_id]
                        state.is_in_billing_queue = True
                        state.billing_queue_entry_time = frame_time
                    break
        if not found and visitor_id in self.states:
            state = self.states[visitor_id]
            is_billing = self.zone_mapper.is_billing_zone(state.current_zone) if self.zone_mapper else False
            if is_billing or (state.current_zone and "BILLING" in state.current_zone.upper()):
                if not state.is_in_billing_queue:
                    self._emit(
                        event_type="BILLING_QUEUE_JOIN",
                        visitor_id=visitor_id,
                        store_id=store_id,
                        camera_id=camera_id,
                        zone_id=state.current_zone,
                        dwell_ms=0,
                        is_staff=state.is_staff,
                        confidence=1.0,
                        frame_time=frame_time,
                        metadata={"queue_depth": queue_depth}
                    )
                    state.is_in_billing_queue = True
                    state.billing_queue_entry_time = frame_time
        return self.flush_pending()

    def handle_billing_abandon(self, visitor_id: str, camera_id: str, 
                               frame_time: datetime, store_id: str) -> List[dict]:
        """
        Emits a BILLING_QUEUE_ABANDON event if the visitor left the queue without checkout.
        """
        if visitor_id not in self.states:
            return []
            
        state = self.states[visitor_id]
        if state.is_in_billing_queue:
            dwell_ms = 0
            if state.billing_queue_entry_time:
                dwell_ms = int((frame_time - state.billing_queue_entry_time).total_seconds() * 1000)
            self._emit(
                event_type="BILLING_QUEUE_ABANDON",
                visitor_id=visitor_id,
                store_id=store_id,
                camera_id=camera_id,
                zone_id=state.current_zone,
                dwell_ms=dwell_ms,
                is_staff=state.is_staff,
                confidence=1.0,
                frame_time=frame_time
            )
            state.is_in_billing_queue = False
        return self.flush_pending()

    def clear_all(self, final_time: datetime) -> List[dict]:
        """
        Forces exit for all tracked visitors.
        """
        events = []
        visitor_ids = list(self.states.keys())
        for visitor_id in visitor_ids:
            state = self.states[visitor_id]
            events.extend(self.handle_exit(
                visitor_id=visitor_id,
                camera_id="CAM_EXIT",
                frame_time=final_time,
                store_id=state.store_id
            ))
        return events

    def flush_pending(self) -> List[dict]:
        """
        Clears and returns the list of pending events.
        """
        events = list(self.pending_events)
        self.pending_events.clear()
        return events

    def _emit(self, event_type: str, visitor_id: str, store_id: str, camera_id: str, 
              zone_id: Optional[str], dwell_ms: int, is_staff: bool, confidence: float, 
              frame_time: datetime, metadata: Optional[dict] = None) -> dict:
        """
        Creates and stores a validated StoreEvent schema dict.
        """
        if visitor_id in self.states:
            state = self.states[visitor_id]
            state.session_seq += 1
            session_seq = state.session_seq
        else:
            session_seq = 0

        if metadata is None:
            metadata = {}
        metadata["session_seq"] = session_seq
        
        # Enforce UTC timezone awareness formatting
        if frame_time.tzinfo is None:
            frame_time = frame_time.replace(tzinfo=timezone.utc)
            
        ts_iso = frame_time.isoformat()
        if ts_iso.endswith("+00:00"):
            ts_iso = ts_iso.replace("+00:00", "Z")

        # Resolve sku_zone if possible
        sku_zone = metadata.get("sku_zone")
        if not sku_zone and zone_id and self.zone_mapper:
            sku_zone = self.zone_mapper.get_zone_sku(zone_id)

        event_metadata = {
            "queue_depth": metadata.get("queue_depth"),
            "sku_zone": sku_zone,
            "session_seq": session_seq,
            **{k: v for k, v in metadata.items() if k not in ["queue_depth", "sku_zone", "session_seq"]}
        }

        event = {
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": camera_id,
            "visitor_id": visitor_id,
            "event_type": event_type,
            "timestamp": ts_iso,
            "zone_id": zone_id,
            "dwell_ms": max(0, int(dwell_ms)),
            "is_staff": is_staff,
            "confidence": float(min(1.0, max(0.0, confidence))),
            "metadata": event_metadata
        }
        self.pending_events.append(event)
        return event

# Export alias for backward compatibility
PipelineStateMachine = StateMachine
