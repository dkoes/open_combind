import os
import gzip
import numpy as np
import pandas as pd
from glob import glob
from plumbum.cmd import obrms
from rdkit.Chem import AllChem as Chem
from utils import basename, mp, mkdir, np_load

IFP = {'rd1':    {'version'           : 'rd1',
                   'level'             : 'residue',
                   'hbond_dist_opt'    : 2.5,
                   'hbond_dist_cut'    : 3.0,
                   'hbond_angle_opt'   : 60.0,
                   'hbond_angle_cut'   : 90.0,
                   'sb_dist_opt'       : 4.0,
                   'sb_dist_cut'       : 5.0,
                   'contact_scale_opt' : 1.25,
                   'contact_scale_cut' : 1.75,},
      }

# add an option to change which score you get from gnina
class Features:
    """
    Organize feature computation and loading.
    """
    def __init__(self, root, ifp_version='rd1', shape_version='pharm_max',
                 mcss_version='mcss16', max_poses=10000, pv_root=None,
                 ifp_features=['hbond', 'saltbridge', 'contact']):
        self.root = os.path.abspath(root)
        if pv_root is None:
            self.pv_root = self.root + '/docking'

        self.ifp_version = ifp_version
        self.shape_version = shape_version
        self.mcss_version = mcss_version
        self.mcss_file = '{}/features/{}.typ'.format(os.environ['COMBINDHOME'], mcss_version)
        self.max_poses = max_poses
        self.ifp_features = ifp_features

        self.raw = {}

    def path(self, name, base=False, pv=None, pv2=None):
        if base:
            return '{}/{}'.format(self.root, name)

        if self.pv_root != self.root+'/docking':
            if pv is not None:
                pv = pv.replace(self.pv_root), self.root+'/single'
            if pv2 is not None:
                pv2 = pv2.replace(self.pv_root), self.root+'/single'

        # single features
        if name == 'rmsd':
            return pv.replace('.sdf.gz', '_rmsd.npy')
        elif name == 'gscore':
            return pv.replace('.sdf.gz', '_gscore.npy')
        elif name == 'name':
            return pv.replace('.sdf.gz', '_name.npy')
        elif name == 'ifp':
            suffix = '_ifp_{}.csv'.format(self.ifp_version)
            return pv.replace('.sdf.gz', suffix)

        # pair features
        elif name == 'shape':
            return f'{self.root}/shape.npy'
        elif name == 'mcss':
            return f'{self.root}/mcss.npy'
        else:
            return f'{self.root}/{name}.npy'

    def load_features(self):
        paths = glob(f'{self.root}/*.npy')
        for path in paths:
            name = path.split('/')[-1][:-4]
            self.raw[name] = np.load(path)

    def get_view(self, ligands, features):
        """
        """
        data = {}
        data['gscore'] = {}
        data['rmsd'] = {}
        for ligand in ligands:
            mask = self.raw['name1'] == ligand
            assert sum(mask)
            data['gscore'][ligand] = self.raw['gscore1'][mask]
            data['rmsd'][ligand] = self.raw['rmsd1'][mask]

        for feature in features:
            data[feature] = {}
            for i, ligand1 in enumerate(ligands):
                for ligand2 in ligands[i+1:]:
                    mask1 = self.raw['name1'] == ligand1
                    mask2 = self.raw['name1'] == ligand2
                    data[feature][(ligand1, ligand2)] = self.raw[feature][mask1, :][:, mask2]

        return data

    def load_single_features(self, pvs, ligands=None):
        rmsds, gscores, poses, names, ifps = [], [], [], [], []
        for pv in pvs:
            _rmsds = np.load(self.path('rmsd', pv=pv))
            _gscores = np.load(self.path('gscore', pv=pv))
            _names = np.load(self.path('name', pv=pv))

            _ifps = pd.read_csv(self.path('ifp', pv=pv))
            _ifps = [_ifps.loc[_ifps.pose==p] for p in range(max(_ifps.pose)+1)]

            sts = Chem.ForwardSDMolSupplier(gzip.open(pv))
            _poses = [st for st in sts]

            keep = []
            for i in range(len(_names)):
                if ((ligands == None or (_names[i] in ligands))
                    and sum(_names[:i] == _names[i]) < self.max_poses):
                    keep += [i]
            rmsds += [_rmsds[keep]]
            gscores += [_gscores[keep]]
            names += [_names[keep]]
            poses += [_poses[i] for i in keep]
            ifps += [_ifps[i] for i in keep]

        rmsds = np.hstack(rmsds)
        names = np.hstack(names)
        gscores = np.hstack(gscores)
        return rmsds, gscores, poses, names, ifps

    def compute_single_features(self, pvs, native_poses):
        # For single features, there is no need to keep sub-sets of ligands
        # separated,  so just merge them at the outset to simplify the rest of
        # the method.
        if type(pvs[0]) == list:
            pvs = [pv for _pvs in pvs for pv in _pvs]

        pvs = [os.path.abspath(pv) for pv in pvs]

        print('Extracting GNINA scores.')
        for pv in pvs:
            out = self.path('gscore', pv=pv)
            if not os.path.exists(out):
                self.compute_gscore(pv, out)

        print('Extracting names.')
        for pv in pvs:
            out = self.path('name', pv=pv)
            if not os.path.exists(out):
                self.compute_name(pv, out)

        print('Computing RMSDs to native poses')
        for pv in pvs:
            out = self.path('rmsd', pv=pv)
            if not os.path.exists(out):
                self.compute_rmsd(pv, native_poses, out)

        print('Computing interaction fingerprints.')
        for pv in pvs:
            out = self.path('ifp', pv=pv)
            if not os.path.exists(out):
                self.compute_ifp(pv, out)

    def compute_pair_features(self, pvs, pvs2=None, ifp=True, shape=True, mcss=True, processes=1):
        mkdir(self.root)
        rmsds1, gscores1, poses1, names1, ifps1 = self.load_single_features(pvs)
        out = self.path('rmsd1')
        np.save(out, rmsds1)
        out = self.path('gscore1')
        np.save(out, gscores1)
        out = self.path('name1')
        np.save(out, names1)
        if pvs2 == None:
            (rmsds2, gscores2, poses2, names2, ifps2
                ) = rmsds1, gscores1, poses1, names1, ifps1
        else:
            rmsds2, gscores2, poses2, names2, ifps2 = self.load_single_features(pvs2)
            out = self.path('rmsd2')
            np.save(out, rmsds2)
            out = self.path('gscore2')
            np.save(out, gscores2)
            out = self.path('name2')
            np.save(out, names2)

        if ifp:
            print('Computing interaction similarities.')
            for feature in self.ifp_features:
                out = self.path(feature)
                if not os.path.exists(out):
                    self.compute_ifp_pair(ifps1, ifps2,  feature, out, processes=processes)

        if shape:
            print('Computing shape similarities.')
            out = self.path('shape')
            if not os.path.exists(out):
                self.compute_shape(poses1, poses2, out)

        if mcss:
            print('Computing mcss similarities.')
            out = self.path('mcss')
            if not os.path.exists(out):
                self.compute_mcss(poses1, poses2, out, processes=processes)

    # Methods to calculate features
    def compute_name(self, pv, out):
        names = []
        sts = Chem.ForwardSDMolSupplier(gzip.open(pv)) 
        docked_fname = os.path.basename(pv).split('.')[0]
        docked_to = docked_fname.split('-to-')[-1]
        for idx, st in enumerate(sts):
            names += [f"{st.GetProp('_Name')}_{str(idx)}-to-{docked_to}"]
            if len(names) == self.max_poses:
                break
        np.save(out, names)

    def compute_gscore(self, pv, out):
        gscores = []
        sts = Chem.ForwardSDMolSupplier(gzip.open(pv)) 
        for st in sts:
            gscores += [float(st.GetProp('CNNaffinity'))]
            if len(gscores) == self.max_poses:
                break
        np.save(out, gscores)

    def compute_rmsd(self, pv, native_poses, out):
        rmsds = []
        name = pv.split('/')[-1].split('-')[0]
        print(name)
        if name in native_poses:
            native = native_poses[name]
            try:
                obrms_out = obrms[native, pv,'--firstonly']()
                messy_rmsds = obrms_out.strip().split('\n')
                rmsds = [float(r.split()[-1]) for r in messy_rmsds]
            except:
                print(f'RMSD failed for {name}')
        else:
            print(name)
            rmsds = [-1] * self.max_poses

        np.save(out, rmsds)

    def compute_ifp(self, pv, out):
        from features.ifp import ifp
        settings = IFP[self.ifp_version]
        ifp(settings, pv, out, self.max_poses)

    def compute_ifp_pair(self, ifps1, ifps2, feature, out, processes=1):
        if processes != 1:
            from features.ifp_similarity import ifp_tanimoto_mp
            tanimotos = ifp_tanimoto_mp(ifps1, ifps2, feature, processes)
        else:
            from features.ifp_similarity import ifp_tanimoto
            tanimotos = ifp_tanimoto(ifps1, ifps2, feature)
        np.save(out, tanimotos)

    def compute_shape(self, poses1, poses2, out):
        from features.shape import shape
        # More efficient to have longer pose list provided as second argument.
        # This only matters for screening.
        sims = shape(poses2, poses1, version=self.shape_version).T
        np.save(out, sims)

    def compute_mcss(self, poses1, poses2, out, processes=1):
        if processes != 1:
            from features.mcss import mcss_mp
            rmsds = mcss_mp(poses1, poses2, self.mcss_file, processes)
        else:
            from features.mcss import mcss
            rmsds = mcss(poses1, poses2, self.mcss_file)
        np.save(out, rmsds)
