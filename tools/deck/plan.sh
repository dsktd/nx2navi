#!/bin/bash
# plan.sh: the measurement queue after Cal's session (deck2, short standing cells through the Steam entry)
N=$HOME/nx2navi; cd $N
./batch.sh field-mid-standing 4200 3 base= p1080=NX2NAVI_GAME_RES=1080 lowend=NX2NAVI_LOW_END_GPU=1 handheld=NX2NAVI_OPERATION_MODE=handheld share50=NX2NAVI_SCENE_SHARE=0.5
./batch.sh field-mid-standing 4200 1 aaoff=NX2NAVI_AA=off aniso=NX2NAVI_ANISO=game shres=NX2NAVI_SHADOW_RES=512 shrange=NX2NAVI_SHADOW_RANGE=50 \
  folred=NX2NAVI_LOW_END_GPU=1,NX2NAVI_FOLIAGE=reduced folcull=NX2NAVI_FOLIAGE_SHADOW_CULL=0 tail=NX2NAVI_REPLAY_ASYNC=0,NX2NAVI_TAIL_EARLY=1 w2=NX2NAVI_REPLAY_WORKERS=2
./batch.sh kakariko-standing 4200 3 kbase= khand=NX2NAVI_OPERATION_MODE=handheld
