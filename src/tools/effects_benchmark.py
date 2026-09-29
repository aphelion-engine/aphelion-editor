"""python -m tools.effects_benchmark --output report.json [--backend python]."""
import argparse
import json
from pathlib import Path
import platform
import statistics
import time
import tracemalloc

import numpy as np


def cases(source):
    from effects.color_adjustments import exposure_contrast, posterize, threshold
    from effects.advanced_color import levels, shadows_highlights, color_balance
    from effects.color_grading import apply_color_grade
    from effects.compositing import blend_frames
    from effects.keying import chroma_key_mask, suppress_spill
    from effects.filters import gaussian_blur
    from effects.transform import transform_2d
    from core.nodes.enums import BlendMode, TransformBorderMode
    return {
        'exposure_contrast': lambda: exposure_contrast(source,exposure=.5,brightness=10,contrast=1.2),
        'posterize': lambda: posterize(source,levels=7),
        'threshold': lambda: threshold(source,level=100,low_color=(10,20,30),high_color=(200,210,220)),
        'levels': lambda: levels(source,in_black=.1,in_white=.9,gamma=1.2,out_black=.05,out_white=.95),
        'shadows_highlights': lambda: shadows_highlights(source,shadows=.2,highlights=.3,balance=.1),
        'color_balance': lambda: color_balance(source,cyan_red=.2,magenta_green=-.2,yellow_blue=.1,preserve_luma=True),
        'color_grade': lambda: apply_color_grade(source,exposure=.4,contrast=1.2,saturation=1.1,temperature=.2,tint=-.1,lift_rgb=(140,128,110),gamma_rgb=(120,145,125),gain_rgb=(125,130,140),amount=.7),
        'overlay': lambda: blend_frames(source,source,mode=BlendMode.Overlay,opacity=.6,mask=source),
        'chroma_key': lambda: chroma_key_mask(source,key_color=(0,255,0),tolerance=.2,softness=.1),
        'spill': lambda: suppress_spill(source,key_color=(0,255,0),amount=.7),
        'gaussian_blur': lambda: gaussian_blur(source,radius=5,sigma=2),
        'transform': lambda: transform_2d(source,translate_x=.1,translate_y=.1,scale=.9,rotation_degrees=10,border_mode=next(iter(TransformBorderMode)),border_color=(0,0,0)),
    }


def main():
    import core.nodes  # initialize the existing node/effects registry in app order
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--backend',choices=['python','native','both'],default='python')
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--effects', default='', help='Comma-separated subset; empty runs all effects')
    parser.add_argument('--sizes', default='1280x720,1920x1080,2560x1440,3840x2160')
    args=parser.parse_args()
    try:
        from effects.native_fx import use_backend
    except ImportError:
        from contextlib import nullcontext
        use_backend=lambda _:nullcontext()
    report={'platform':platform.platform(),'backend':args.backend,'repeats':args.repeats,'results':[]}
    from render.resource_limits import export_thread_budget
    backends = ['python', 'native'] if args.backend == 'both' else [args.backend]
    selected = set(args.effects.split(',')) if args.effects else None
    sizes = [tuple(map(int, size.split('x'))) for size in args.sizes.split(',')]
    with export_thread_budget():
        for width,height in sizes:
            source=np.random.default_rng(123).random((height,width,3),dtype=np.float32)
            for name,call in cases(source).items():
                if selected is not None and name not in selected:
                    continue
                for backend in backends:
                  with use_backend(backend):
                    result=call()
                    del result
                    samples=[]; cpu=[]
                    for _ in range(args.repeats):
                        started=time.perf_counter(); cpu_start=time.process_time()
                        result=call()
                        samples.append((time.perf_counter()-started)*1000)
                        cpu.append((time.process_time()-cpu_start)*1000)
                        del result
                    tracemalloc.start(); result=call(); _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
                    row={'effect':name,'backend':backend,'width':width,'height':height,'median_ms':statistics.median(samples),
                         'samples_ms':samples,'cpu_ms':statistics.median(cpu),'python_numpy_peak_bytes':peak}
                    report['results'].append(row);print(json.dumps(row),flush=True)
                    args.output.parent.mkdir(parents=True,exist_ok=True)
                    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
                    del result


if __name__=='__main__':
    main()
