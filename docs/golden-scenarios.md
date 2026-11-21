# DEMO 黄金样本

德国 Klarna，24h，全部终端。基准 3800/4000，当前 1784/2000，相差 −5.8pp。当前 Android 为 850/1000，Web 为 934/1000。Android 失败样本中 90/150 为 redirect_timeout。该归一化演示错误码只支持优先排查回跳链路的假设。独立 SQL 复算见 tests/week01/test_golden.py。
