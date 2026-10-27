"""
Запуск фоновых загрузчиков (QThread с сигналом done).

Если загрузчик пересоздать, пока прежний ещё работает (быстрые повторные
нажатия, медленная база), Python теряет ссылку на работающий QThread и
Qt аварийно завершает программу: «QThread: Destroyed while thread is still
running». Здесь каждый поток живёт до своего завершения, а результат
устаревшего запроса отбрасывается — на экран попадает только последний.
"""

_alive = set()  # потоки, которые ещё работают


class LoaderSlot:
    """Место для одного загрузчика: start() заменяет текущий, slot получает
    результат (аргументы сигнала done) только от последнего запущенного."""

    def __init__(self, slot):
        self._slot = slot
        self._current = None

    def start(self, thread):
        self._current = thread
        _alive.add(thread)
        thread.done.connect(lambda *args, t=thread: self._deliver(t, args))
        thread.finished.connect(lambda t=thread: _release(t))
        thread.start()

    def _deliver(self, thread, args):
        if thread is self._current:
            self._slot(*args)


def _release(thread):
    # finished приходит, когда поток уже почти вышел; wait() дожидается
    # окончательного выхода, после чего объект можно отпустить
    thread.wait()
    _alive.discard(thread)
