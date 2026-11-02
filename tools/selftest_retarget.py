"""Self-test for tools/retarget.py.

We take our own medic rig, build a *fake foreign* rig from it:
  * every bone gets a different rest orientation (random rotations),
  * bone names become mixamo-like (mixamorig:Hips, mixamorig:LeftArm ...),
  * an extra bone (Spine1) is inserted between Hips and Spine, as Mixamo does,
and then we bake one of our own clips into that foreign rig by expressing, at
every frame, the same *world* orientation our character has.  If the retargeting
math is right, the round trip must give back our original local rotations.

usage: python tools/selftest_retarget.py
"""
import json
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import glb_io
import glbw
import retarget as RT
import rig as RIG

MIXAMO = {
    'Root': 'mixamorig:Hips',      # Root merges into the hips in Mixamo rigs
    'Hips': 'mixamorig:Hips',
    'Spine': 'mixamorig:Spine1',
    'Chest': 'mixamorig:Spine2',
    'Neck': 'mixamorig:Neck',
    'Head': 'mixamorig:Head',
    'Shoulder_L': 'mixamorig:LeftShoulder', 'UpperArm_L': 'mixamorig:LeftArm',
    'LowerArm_L': 'mixamorig:LeftForeArm', 'Hand_L': 'mixamorig:LeftHand',
    'Shoulder_R': 'mixamorig:RightShoulder', 'UpperArm_R': 'mixamorig:RightArm',
    'LowerArm_R': 'mixamorig:RightForeArm', 'Hand_R': 'mixamorig:RightHand',
    'Thigh_L': 'mixamorig:LeftUpLeg', 'Shin_L': 'mixamorig:LeftLeg',
    'Foot_L': 'mixamorig:LeftFoot',
    'Thigh_R': 'mixamorig:RightUpLeg', 'Shin_R': 'mixamorig:RightLeg',
    'Foot_R': 'mixamorig:RightFoot',
}


def q_to_gl(q):
    return [q[1], q[2], q[3], q[0]]


def build_fake_source(dst, clip_rot, clip_hips, out_path, fps=30.0):
    """Write a foreign rig whose animation reproduces our world-space motion."""
    rng = np.random.default_rng(5)
    srct_names = {v for v in MIXAMO.values()}
    # extra bone between Hips and Spine, as in Mixamo
    order = ['mixamorig:Hips', 'mixamorig:Spine1', 'mixamorig:Spine2']
    nodes = {}
    g = glbw.GLB('FakeSource')
    # hierarchy: hips -> spine1 -> spine2 -> neck/head/shoulders
    parent_of = {}
    for tname, sname in MIXAMO.items():
        p = dst.parent[tname]
        if p is None:
            continue
        if MIXAMO[p] == sname:
            continue          # Root and Hips merge into the hips bone
        parent_of[sname] = MIXAMO[p]
    # our Root has no parent: it becomes the fake hips (already is)
    for name in nodes:
        pass
    # build a node per unique source bone
    uniq = []
    for t in dst.names:
        s = MIXAMO[t]
        if s not in uniq:
            uniq.append(s)
    # random rest orientations (relative to our rest), so the retarget must correct
    rest_rot = {}
    for s in uniq:
        rest_rot[s] = RT.q_from_mat(RIG.rot_euler(*rng.normal(0, 0.5, 3)))
    # Place the foreign rest skeleton so that its bone *positions* match ours
    # (only the orientations differ) - then the round trip must be exact.
    def mapped_tname(s):
        return [k for k, v in MIXAMO.items() if v == s][-1]

    for s in uniq:
        nodes[s] = g.node(s)

    fake_R = {}
    for s in uniq:
        p = parent_of.get(s)
        fake_R[s] = (fake_R[p] if p in fake_R else np.eye(3)) @ RT.mat_from_q(rest_rot[s])
    P_of = {}
    for s in uniq:
        P_of[s] = dst.rest_world[mapped_tname(s)][:3, 3].copy()
    for s in uniq:
        p = parent_of.get(s)
        if p in uniq:
            tloc = (fake_R[p].T @ (P_of[s] - P_of[p]))
        else:
            tloc = P_of[s]
        tname = mapped_tname(s)
        g.g['nodes'][nodes[s]]['translation'] = [float(x) for x in tloc]
        g.g['nodes'][nodes[s]]['rotation'] = q_to_gl(rest_rot[s])
    for s in uniq:
        p = parent_of.get(s)
        if p and p in nodes:
            g.g['nodes'][nodes[p]].setdefault('children', []).append(nodes[s])
    roots = [nodes[s] for s in uniq if parent_of.get(s) not in nodes]
    g.g['scenes'][0]['nodes'] = [roots[0]]

    # ---- animation: reproduce our world rotations with the foreign rest
    times = np.array(clip_rot['times'], np.float32)

    samplers, channels = [], []
    t_acc = g.accessor(times)

    # our world rotations per frame
    world = {}
    for tname in dst.names:
        p = dst.parent[tname]
        local = np.array(clip_rot['rot'][tname])
        base = world[p] if p else np.array([[1.0, 0, 0, 0]] * len(local))
        world[tname] = [RT.q_mul(base[i], local[i]) for i in range(len(local))]

    # What a real foreign clip looks like to a retargeter: the source bone moves
    # *relative to its own rest* by the same world delta our bone has relative to
    # ours.  world_src(t) = R_src_rest * inv(R_dst_rest) * world_dst(t)
    src_world = {}
    for s in uniq:
        tname = mapped_tname(s)
        R_src = fake_R[s]
        R_dst = dst.rest_world[tname][:3, :3]
        src_world[s] = [R_src @ R_dst.T @ RT.mat_from_q(w) for w in world[tname]]

    for s in uniq:
        qs = []
        for i in range(len(times)):
            ws = src_world[s][i]
            pname = parent_of.get(s)
            if pname in src_world:
                ws = src_world[pname][i].T @ ws
            qs.append(RT.q_from_mat(ws))
        q = np.array([q_to_gl(x) for x in qs])
        for i in range(1, len(q)):
            if float(np.dot(q[i], q[i - 1])) < 0:
                q[i] = -q[i]
        qacc = g.accessor(q.astype(np.float32))
        samplers.append({'input': t_acc, 'output': qacc, 'interpolation': 'LINEAR'})
        channels.append({'sampler': len(samplers) - 1,
                         'target': {'node': nodes[s], 'path': 'rotation'}})

    # hips: same delta, expressed in the source's world frame
    root_w = dst.rest_world['Root']
    hips_rest_dst = dst.rest_world['Hips']
    hips_rest_src = P_of[MIXAMO['Hips']]
    fix = dst.rest_world['Root'][:3, :3] @ fake_R[MIXAMO['Hips']].T
    hips_w = []
    for loc in clip_hips:
        world_p = root_w[:3, :3] @ np.asarray(loc, float) + root_w[:3, 3]
        delta = fix.T @ (world_p - hips_rest_dst[:3, 3])
        hips_w.append(hips_rest_src + delta)
    hips = np.array(hips_w, np.float32)
    pacc = g.accessor(hips)
    samplers.append({'input': t_acc, 'output': pacc, 'interpolation': 'LINEAR'})
    channels.append({'sampler': len(samplers) - 1,
                     'target': {'node': nodes[MIXAMO['Hips']], 'path': 'translation'}})
    g.g['animations'].append({'name': 'Test', 'samplers': samplers, 'channels': channels})
    g.write(out_path)
    return out_path


def main():
    dst = RT.Skeleton('game/models/medic.glb')
    fx = RT.read_clip('game/models/medic.glb')[0]
    clip = fx['Walk']
    res = RT.retarget_clip(clip, dst, dst, {n: n for n in dst.names}, fps=30.0,
                           ref='bind', mode='rot')
    src_path = '/tmp/fake_source.glb'
    build_fake_source(dst, res, res['hips'], src_path)

    # ---- now retarget the fake clip back onto our rig
    clips, sjs, _ = RT.read_clip(src_path)
    src_rig = RT.RigData(src_path)
    mapping = RT.build_mapping(src_rig.names, dst.names)
    print('mapping:')
    for k in dst.names:
        print(f'  {k:12s} <- {mapping.get(k)}')
    mapping = {k: v for k, v in mapping.items() if v is not None}
    back = RT.retarget_clip(clips['Test'], src_rig, dst, mapping, fps=30.0,
                            ref='bind', mode='rot')

    worst = 0.0
    for b in dst.names:
        a = np.array(res['rot'][b])
        c = np.array(back['rot'][b])
        for i in range(len(a)):
            d = min(np.linalg.norm(a[i] - c[i]), np.linalg.norm(a[i] + c[i]))
            worst = max(worst, float(d))
    hips_a = np.array(res['hips'])
    hips_c = np.array(back['hips'])
    hips_err = float(np.abs(hips_a - hips_c).max())
    print(f'  1) math round trip : max q err {worst:.6f}, max hips err {hips_err:.5f} m')

    # ---- stage 2: the file we write must play the same motion in engine
    out = '/tmp/selftest_clips.glb'
    RT.write_clip_glb(dst, [('Test', back)], out)
    disk = RT.RigData(out)
    disk_clips, _, _ = RT.read_clip(out)
    clip_d = disk_clips['Test']
    worst_file = 0.0
    for i, t in enumerate(back['times']):
        world = {}
        for b in disk.names:
            base = world[disk.parent[b]] if disk.parent[b] else np.eye(3)
            Rw, _ = None, None
            tr = clip_d['tracks'].get(b, {})
            if 'rotation' in tr:
                times_q, vals_q = tr['rotation']
                k = max(0, min(int(np.searchsorted(times_q, t) - 1), len(times_q) - 2))
                f = (t - times_q[k]) / max(times_q[k + 1] - times_q[k], 1e-9)
                q = RT.q_slerp(vals_q[k], vals_q[k + 1], min(max(f, 0.0), 1.0))
            else:
                q = disk.rest_q[b]
            world[b] = base @ RT.mat_from_q(q)
            want = RT.mat_from_q(np.array(back['rot'][b])[i])
            wantw = (world[disk.parent[b]] if disk.parent[b] else np.eye(3)) @ want
            err = float(np.abs(world[b] - wantw).max())
            worst_file = max(worst_file, err)
    print(f'  2) written GLB     : max bone matrix err {worst_file:.6f}')
    print(f'     rig node name   : {disk.root_name} ({len(disk_clips["Test"]["tracks"])} animated bones)')

    worst = max(worst, worst_file)
    print(f'\nmax quaternion error: {worst:.6f}   max hips error: {hips_err:.5f} m')
    ok = worst < 0.02 and hips_err < 0.02
    print('SELFTEST', 'OK' if ok else 'FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
