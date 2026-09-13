"""Compare synthetic graph/curve hot paths against the checked-in baseline.

Run from the editor root with .venv/Scripts/python scripts/benchmark_tracking_performance.py.
This does not load user media or modify projects; results are microbenchmarks, not playback FPS.
"""
from pathlib import Path
import sys, subprocess, types, time, json, argparse
import numpy as np
import cv2
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from core.project import Project
from core.nodes.base import Node,NodeSocketType
from core.animation.curve import interpolate_curve


def baseline_module(path,name,revision):
    source=subprocess.check_output(["git","show",f"{revision}:{path}"],text=True,encoding="utf-8")
    module=types.ModuleType(name)
    sys.modules[name]=module
    exec(compile(source,path,"exec"),module.__dict__)
    return module


class MultiOutput(Node):
    node_type="Benchmark Multi Output"
    def __init__(self):
        self.calls=0
        self.source=np.random.default_rng(0).random((360,640,3),dtype=np.float32)
        super().__init__()
    def _setup_sockets(self):
        for i in range(8):
            self.add_output(str(i),NodeSocketType.Number)
    def evaluate(self,frame):
        self.calls+=1
        result=cv2.GaussianBlur(self.source,(21,21),3)
        value=float(result.mean())
        return {str(i):value+i for i in range(8)}


def graph_time(project_cls):
    project=project_cls("benchmark")
    node=MultiOutput()
    project.add_node(node,"multi")
    start=time.perf_counter()
    total=0.0
    for frame in range(30):
        for output in range(8):
            total+=project.evaluate_node("multi",frame,str(output))
    return time.perf_counter()-start,node.calls,total


def curve_time(function):
    keys={frame:frame/10000 for frame in range(10000)}
    start=time.perf_counter()
    total=sum(function(keys,frame) for frame in range(1000,2000))
    return time.perf_counter()-start,total


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--baseline",required=True,help="Git revision before the optimization")
    revision=parser.parse_args().baseline
    old_project=baseline_module("src/core/project.py","benchmark_project_baseline",revision).Project
    old_curve=baseline_module("src/core/animation/curve.py","benchmark_curve_baseline",revision).interpolate_curve
    graph_time(Project)  # Warm OpenCV before both measurements.
    before=graph_time(old_project)
    after=graph_time(Project)
    curve_before=curve_time(old_curve)
    curve_after=curve_time(interpolate_curve)
    assert np.isclose(before[2],after[2])
    assert np.isclose(curve_before[1],curve_after[1])
    print(json.dumps({"baseline":revision,"graph":{"before_seconds":before[0],"after_seconds":after[0],
        "before_evaluations":before[1],"after_evaluations":after[1],"speedup":before[0]/after[0]},
        "dense_curves":{"before_seconds":curve_before[0],"after_seconds":curve_after[0],
        "speedup":curve_before[0]/curve_after[0]}},indent=2))
