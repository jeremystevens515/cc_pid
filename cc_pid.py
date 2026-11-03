#!/usr/bin/env python3

import os
import json
import logging
import time
import uuid
import requests

from models import (
    SessionConfig, CoolerControlSessionClient, ConfigurationWatcher,
    PIDConfig, PIDController, PIDSupervisoryController, TempSource,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("cc_pid")

log.info("Using config file: %s", CONFIG_PATH)


def load_config(path):
    supervisory_controllers = []

    with open(path, "r") as file:
        config_data = json.load(file)

    for scontrol in config_data["supervisory_controllers"]:
        try:
            name = scontrol["name"]

            temp_source = TempSource(
                temp_name = scontrol["temp_source"]["temp_name"],
                device_uid = scontrol["temp_source"]["device_uid"],
            )

            controller = PIDController(PIDConfig(**scontrol["pid_config"]))

            profile_uid = scontrol["profile_uid"]

            uid = scontrol["uid"]

            new_sc = PIDSupervisoryController(
                name = name,
                temp_source = temp_source,
                controller = controller,
                profile_uid = profile_uid,
                uid = uid
            )

            supervisory_controllers.append(new_sc)

            log.info(f"Initialized PID Supervisory Controller '{new_sc.name}', monitoring {new_sc.temp_source.temp_name} on device {new_sc.temp_source.device_uid}, controlling profile {new_sc.profile_uid}. Settings: target_temp={new_sc.controller.config.target_temp}°C, deadband={new_sc.controller.config.deadband}°C, deadband_offset={new_sc.controller.config.deadband_offset}°C, min_duty={new_sc.controller.config.min_duty}%, target_duty={new_sc.controller.config.target_duty}%, max_duty={new_sc.controller.config.max_duty}%, Kp={new_sc.controller.config.kp}, Ki={new_sc.controller.config.ki}, Kd={new_sc.controller.config.kd}")

        except Exception:
            log.exception(f"Failed to initialize PID Supervisory Controller")
            continue

    return supervisory_controllers


def main():
    session_config = SessionConfig()
    client = CoolerControlSessionClient(session_config)
    poll_interval_s = 1

    supervisory_controllers = load_config(CONFIG_PATH)
    profile_cache = client.get_profiles()
    '''watcher = ConfigurationWatcher(CONFIG_PATH)'''

    while True:
        for sc in supervisory_controllers:

            '''if sc.watcher is not None:
                sc.watcher.check_and_reload(sc.controller)'''

            try:
                temp = client.get_temp(sc.temp_source.device_uid, sc.temp_source.temp_name)

                if sc.controller.safety_check(temp):
                    duty = 100
                else:
                    duty = sc.controller.update(temp)

                if duty != sc.last_duty:
                    client.set_duty(profile_cache, sc.profile_uid, duty)
                    log.info(f"[{sc.name}] temp={temp}°C -> duty={duty}%%")
                    sc.last_duty = duty
                else:
                    log.debug(f"[{sc.name}] temp={temp}°C -> duty unchanged ({duty}%%)")

            except requests.RequestException as e:
                log.warning(f"[{sc.name}] API call failed, will retry: {e}")
            except Exception:
                log.exception(f"[{sc.name}] Unexpected error in control loop")

        time.sleep(poll_interval_s)


if __name__ == "__main__":
    main()