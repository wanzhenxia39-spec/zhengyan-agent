"""后台定时：按间隔扫描已订阅的股票、把模拟盘推进到今天。没有变化不产生提醒。"""
import logging
import threading

from advisor.services import Services

log = logging.getLogger("advisor.scheduler")


class Scheduler:
    def __init__(self, services: Services, interval_hours: float):
        self.services = services
        self.interval_s = interval_hours * 3600
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="advisor-scheduler", daemon=True)

    def start(self) -> "Scheduler":
        if self.interval_s > 0:
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def tick(self) -> None:
        alerts = self.services.watch.scan_all(log=log.info)
        points = self.services.strategy.step_all(log=log.info)
        log.info("定时任务：新提醒 %d，模拟盘推进 %d", len(alerts), len(points))

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.tick()
            except Exception:       # 定时任务失败不影响服务
                log.exception("定时任务失败")
