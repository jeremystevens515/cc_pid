#!/usr/bin/env python3

import json
import logging
import os
import time
import requests
import uuid

from dataclasses import dataclass, field, fields
from typing import Optional

log = logging.getLogger("cc_auto.models")


#***PROPORTIONAL-INTEGRAL-DERIVATIVE CONTROLLER****
#--------------------------------------------------
#--------------------------------------------------
#   CONFIGURATION
#--------------------------------------------------
class PIDConfig:
    def __init__(
        self,
        target_temp: float = 70.0,
        deadband: float = 0,
        deadband_offset: float = 0,
        min_duty: int = 20,
        target_duty: int = 70,
        max_duty: int = 100,
        critical_temp: int = 87,
        safety_margin: int = 5,
        kp: float = 2.0, # duty% per degree of error
        ki: float = 0.05, # duty% per (degree * sec) of accumulated error
        kd: float = 3,
        d_filter_n: int = 3
    ):
        self.target_temp = float(target_temp)
        self.deadband = float(deadband)
        self.deadband_offset = float(deadband_offset)
        self.deadband_high = self.target_temp + (self.deadband + self.deadband_offset)
        self.deadband_low = self.target_temp - (self.deadband - self.deadband_offset)
        self.min_duty = int(float((min_duty)))
        self.target_duty = int(float((target_duty)))
        self.max_duty = int(float((max_duty)))
        self.critical_temp = int(float((critical_temp)))
        self.safety_margin = int(float((safety_margin)))
        self.kp = float(kp)
        self.ki = float(ki)
        self.kd = float(kd)
        self.d_filter_n = int(d_filter_n)

'''@dataclass
class PIDConfig:
    target_temp: float = 70.0
    deadband: float = 0
    deadband_offset: float = 0
    deadband_high: float = field(init=False)
    deadband_low: float = field(init=False)

    min_duty: int = 20
    target_duty: int = 70
    max_duty: int = 100

    critical_temp: int = 87
    safety_margin: int = 5

    kp: float = 2.0 # duty% per degree of error
    ki: float = 0.05 # duty% per (degree * sec) of accumulated error
    kd: float = 3
    d_filter_n: int = 3

    def __post_init__(self):
        self.deadband_high = self.target_temp + (self.deadband + self.deadband_offset)
        self.deadband_low = self.target_temp - (self.deadband - self.deadband_offset)

    @classmethod
    def from_dict(cls, data: dict) -> "PIDConfig":
        kwargs = {}
        for f in fields(cls):
            if not f.init:
                continue  # deadband_high/deadband_low are derived, not settable
            if f.name not in data:
                continue  # missing -> dataclass default applies
            value = data[f.name]
            if value is None:
                continue
            if f.type in (float, "float") and isinstance(value, str):
                value = float(value)
            elif f.type in (int, "int") and isinstance(value, str):
                value = int(value)
            kwargs[f.name] = value
        return cls(**kwargs)'''
#--------------------------------------------------
#   PROPORTIONAL-INTEGRAL CALCULATIONS
#--------------------------------------------------
class PIDController:
    def __init__(self, config: PIDConfig):
        self.config = config
        self.integral = 0.0
        self.last_time = None
        self.safety_enabled = False
        self.last_error = None
        self.filtered_deriv = 0.0
        self.uid = field(default_factory=lambda: str(uuid.uuid4()))



    def _error(self, current_temp: float):
        if current_temp > self.config.deadband_high:
            return current_temp - self.config.deadband_high # positive if too hot
        if current_temp < self.config.deadband_low:
            return current_temp - self.config.deadband_low # negative if too cool
        return 0.0

    def update(self, current_temp: float) -> int:
        now = time.monotonic()
        dt = 0.0 if self.last_time is None else (now - self.last_time)
        self.last_time = now

        error = self._error(current_temp)
        p_term = self.config.kp * error
        potential_integral = self.integral + (error * dt)
        i_term = potential_integral * self.config.ki
        raw_deriv = 0.0 if (self.last_error is None or dt == 0.0) else (error - self.last_error) / dt
        self.filtered_deriv += (raw_deriv - self.filtered_deriv) / self.config.d_filter_n
        self.last_error = error
        d_term = self.config.kd * self.filtered_deriv

        duty = self.config.target_duty + p_term + i_term + d_term

        #saturation block
        is_saturated_high = (duty >= self.config.max_duty) and (error > 0)
        is_saturated_low = (duty <= self.config.min_duty) and (error < 0)

        if not (is_saturated_high or is_saturated_low):
            self.integral = potential_integral
        else:
            i_term = self.integral * self.config.ki
            duty = self.config.target_duty + p_term + i_term

        duty = max(self.config.min_duty, min(self.config.max_duty, duty))

        log.debug(f"temp={current_temp} error={error} P={p_term} I={i_term} integral={self.integral} duty={duty}")

        return round(duty)

    def safety_check(self, current_temp: float) -> bool:
        if current_temp >= self.config.critical_temp:
            if not self.safety_enabled:
                log.warning(
                    f"SAFETY OVERRIDE: temp={current_temp}°C >= critical={self.config.critical_temp}°C -- forcing 100%% duty"
                )
            self.safety_enabled = True
        elif self.safety_enabled and current_temp <= (self.config.critical_temp - self.config.safety_margin):
            log.info(f"Safety override released: temp={current_temp}°C")
            self.safety_enabled = False
        return self.safety_enabled


#***************CONFIGURATION WATERCH**************
#--------------------------------------------------
#--------------------------------------------------
#   CONFIGURATION & LOGIC
#--------------------------------------------------
class ConfigurationWatcher:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.last_mtime = 0.0

    def check_and_reload(self, controller: PIDController):
        log.debug(f"Watching {self.file_path} (exists={os.path.exists(self.file_path)})")
        if not os.path.exists(self.file_path):
            return

        pi_config = controller.config

        try:
            current_mtime = os.path.getmtime(self.file_path)
            if current_mtime <= self.last_mtime:
                return

            with open(self.file_path, 'r') as file:
                data = json.load(file)

            old_ki = pi_config.ki

            for key, value in data.items():
                setattr(pi_config, key, value)
            pi_config.__post_init__()

            if controller is not None and pi_config.ki != old_ki:
                if old_ki != 0 and pi_config.ki != 0:
                    controller.integral *= (old_ki / pi_config.ki)
                    log.info(f"ki changed {old_ki} -> {pi_config.ki}; rescaled integral to preserve i_term continuity")
                else:
                    controller.integral = 0.0
                    log.info(f"ki changed {old_ki} -> {pi_config.ki}; reset integral (no valid rescale ratio)")

            self.last_mtime = current_mtime

            log.info(f"Runtime configuration reloaded. File path: {self.file_path}. New settings: target_temp={pi_config.target_temp}, deadband={pi_config.deadband}, deadband_offset={pi_config.deadband_offset}, min_duty={pi_config.min_duty}, target_duty={pi_config.target_duty}, max_duty={pi_config.max_duty}, kp={pi_config.kp}, ki={pi_config.ki}, kd={pi_config.kd}")

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            log.error(f"Failed to parse config update. Keeping previous settings. ERROR: {e}")


#******************COOLERCONTROL*******************
#--------------------------------------------------
#--------------------------------------------------
#   CONFIGURATION
#--------------------------------------------------
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token")

def _load_token() -> str:
    """COOLERCONTROL_TOKEN env var wins; otherwise read the 'token' file next to this module."""
    token = os.environ.get("COOLERCONTROL_TOKEN", "").strip()
    if token:
        return token
    try:
        with open(TOKEN_FILE, "r") as f:
            return f.read().strip()
    except OSError:
        return ""

@dataclass
class SessionConfig:
    base_url: str = os.environ.get("COOLERCONTROL_URL", "http://localhost:11987").rstrip("/")
    auth_token: str = field(default_factory=_load_token)

#--------------------------------------------------
#   SESSION CLIENT
#--------------------------------------------------
class CoolerControlSessionClient:
    def __init__(self, config: SessionConfig):
        self.config = config
        self.session = requests.Session()
        if config.auth_token:
            self.session.headers.update({
                "Authorization": f"Bearer {config.auth_token}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            })

    def get_profiles(self):
        url = f"{self.config.base_url}/profiles"
        resp = self.session.get(url, timeout=5)
        resp.raise_for_status()
        return {p["uid"]: p for p in resp.json()["profiles"]}

    def get_temp(self, fan_device_uid: str, temp_sensor_name: str) -> float:
        url = f"{self.config.base_url}/status/{fan_device_uid}/channels/{temp_sensor_name}"
        resp = self.session.get(url, timeout=5)
        resp.raise_for_status()

        data = resp.json()

        try:
            return float(data["status_history"][0]["temps"][0]["temp"])
        except Exception as e:
            raise RuntimeError(f"Could not find temp '{temp_sensor_name}' on device {fan_device_uid}") from e

    def set_duty(self, profile_cache: dict[str, dict], profile_uid: str, duty: int):
        profile = profile_cache.get(profile_uid)
        if profile is None:
            log.error(f"Profile UID {profile_uid} not found in this pass's profile cache")
            return
        
        url = f"{self.config.base_url}/profiles"
        profile["speed_fixed"] = duty

        put_resp = self.session.put(url, json=profile, timeout=5)

        if not put_resp.ok:
            log.error(f"PUT /profiles failed for {profile_uid}: {put_resp.text}")
        put_resp.raise_for_status()


#************PID SUPERVISORY CONTROLLER************
#--------------------------------------------------
#--------------------------------------------------
#   CONFIGURATION
#--------------------------------------------------
@dataclass
class TempSource:
    temp_name: str
    device_uid: str

@dataclass
class PIDSupervisoryController:
    name: str
    temp_source: TempSource
    controller: PIDController
    '''watcher: ConfigurationWatcher'''
    profile_uid: str
    last_duty: int = None
    uid: str = field(default_factory=lambda: str(uuid.uuid4()))