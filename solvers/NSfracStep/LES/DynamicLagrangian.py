__author__ = 'Joakim Boe <joakim.bo@mn.uio.no>'
__date__ = '2015-02-04'
__copyright__ = 'Copyright (C) 2015 ' + __author__
__license__  = 'GNU Lesser GPL version 3 or any later version'

from dolfin import FunctionSpace, TrialFunction, TestFunction, Function, sym,\
        grad, dx, inner, sqrt, TrialFunction, project, assemble, CellVolume,\
        LagrangeInterpolator, DirichletBC, KrylovSolver
from DynamicModules import tophatfilter, lagrange_average, compute_Lij,\
        compute_Mij, dyn_u_ops
import numpy as np
from common import derived_bcs
from fenicstools import compiled_gradient_module

__all__ = ['les_setup', 'les_update']

def les_setup(u_, dt, mesh, assemble_matrix, CG1Function, nut_krylov_solver,
        u_components, bcs, DynamicSmagorinsky, V, **NS_namespace):
    """
    Set up for solving the Germano Dynamic LES model applying
    Lagrangian Averaging.
    """
    
    # Create function spaces
    CG1 = FunctionSpace(mesh, "CG", 1)
    p, q = TrialFunction(CG1), TestFunction(CG1)
    p2 = TrialFunction(V)
    dim = mesh.geometry().dim()
    
    DG = FunctionSpace(mesh, "DG", 0)
    # Define delta and project delta**2 to CG1
    delta = Function(DG)
    delta.vector().zero()
    delta.vector().axpy(1.0, assemble(TestFunction(DG)*dx))
    delta.vector().set_local(delta.vector().array()**(1./dim))
    delta.vector().apply('insert')
    delta_CG1_sq = project(delta, CG1)
    delta_CG1_sq.vector().set_local(delta_CG1_sq.vector().array()**2)
    delta_CG1_sq.vector().apply("insert")
    delta_CG1_sq = delta_CG1_sq.vector()

    # Define nut_
    Sij = sym(grad(u_))
    magS = sqrt(2*inner(Sij,Sij))
    Cs = Function(CG1)
    nut_form = Cs * delta**2 * magS
    # Create nut_ BCs and nut_
    bcs_nut = derived_bcs(CG1, bcs['u0'], u_)
    nut_ = CG1Function(nut_form, mesh, method=nut_krylov_solver, bcs=bcs_nut, bounded=True, name="nut")

    # Create CG1 bcs for velocity components
    bcs_u_CG1 = dict()
    for ui in u_components:
        bcs_CG1 = []
        for bc in bcs[ui]:
            val = bc.value()
            sbd = bc.user_sub_domain()
            bcs_CG1.append(DirichletBC(CG1, bc.value(), bc.user_sub_domain()))
        bcs_u_CG1[ui] = bcs_CG1

    # Create functions for holding the different velocities
    u_CG1 = [Function(CG1) for i in range(dim)]
    # Check vdegree; will become True only if the FunctionSpaces are 100% equal
    vdegree = 1 if len(u_[0].vector().array()) == len(u_CG1[0].vector().array()) else None
    u_filtered = [Function(CG1) for i in range(dim)]
    u_filtered_CG2 = [Function(V) for i in range(dim)]
    dummy = Cs.vector().copy()
    ll = LagrangeInterpolator()

    # Assemble required filter matrices and functions
    G_under = assemble(TestFunction(CG1)*dx)
    G_under.set_local(1./G_under.array())
    G_under.apply("insert")
    G_matr = assemble(inner(p,q)*dx)
    
    # Check if case is 2D or 3D and set up uiuj product pairs and 
    # Sij forms, assemble required matrices
    if dim == 3:
        tensdim = 6
        uiuj_pairs = ((0,0),(0,1),(0,2),(1,1),(1,2),(2,2))
    else:
        tensdim = 3
        uiuj_pairs = ((0,0),(0,1),(1,1))
    # Set up functions for Lij and Mij
    Lij = [dummy.copy() for i in range(tensdim)]
    Mij = [dummy.copy() for i in range(tensdim)]
    Sijcomps = [dummy.copy() for i in range(tensdim)]
    Sijfcomps = [dummy.copy() for i in range(tensdim)]
    # Assemble some required matrices for solving for rate of strain terms
    Sijmats = [assemble_matrix(p2.dx(i)*q*dx) for i in range(dim)]
    # Setup Sij krylov solver
    Sij_sol = KrylovSolver("bicgstab", "jacobi")
    Sij_sol.parameters["preconditioner"]["structure"] = "same_nonzero_pattern"
    Sij_sol.parameters["error_on_nonconvergence"] = False
    Sij_sol.parameters["monitor_convergence"] = False
    Sij_sol.parameters["report"] = False

    # Set up Lagrange functions
    JLM = Function(CG1)
    # Initialize to given number
    JLM.vector()[:] += DynamicSmagorinsky["JLM_init"]
    JMM = Function(CG1)
    # Initialize to given number
    JMM.vector()[:] += DynamicSmagorinsky["JMM_init"]
    lag_dt = DynamicSmagorinsky["Cs_comp_step"]*dt
    first_lag_step = [True]

    return dict(Sij=Sij, nut_form=nut_form, nut_=nut_, delta=delta, bcs_nut=bcs_nut,
                delta_CG1_sq=delta_CG1_sq, CG1=CG1, DG=DG, Cs=Cs, u_CG1=u_CG1, 
                u_filtered=u_filtered, ll=ll, Lij=Lij, Mij=Mij, Sijcomps=Sijcomps, 
                Sijfcomps=Sijfcomps, Sijmats=Sijmats, JLM=JLM, JMM=JMM, dim=dim, 
                tensdim=tensdim, G_matr=G_matr, G_under=G_under, dummy=dummy, 
                uiuj_pairs=uiuj_pairs, Sij_sol=Sij_sol, bcs_u_CG1=bcs_u_CG1,
                vdegree=vdegree, lag_dt=lag_dt, first_lag_step=first_lag_step,
                u_filtered_CG2=u_filtered_CG2) 
    
def les_update(u_ab, u_components, nut_, nut_form, dt, CG1, delta, tstep, 
            DynamicSmagorinsky, Cs, u_CG1, u_filtered, Lij, Mij, vdegree,
            JLM, JMM, dim, tensdim, G_matr, G_under, ll, dummy, uiuj_pairs, 
            Sijmats, Sijcomps, Sijfcomps, delta_CG1_sq, Sij_sol, bcs_u_CG1,
            lag_dt, Smagorinsky, first_lag_step, u_filtered_CG2, **NS_namespace):

    # Check if Cs is to be computed, if not update nut_ and break
    if tstep%DynamicSmagorinsky["Cs_comp_step"] != 0:
        # Update nut_
        nut_()
        # Break function
        return
    
    # All velocity components must be interpolated to CG1 then filtered, also apply bcs
    dyn_u_ops(**vars())

    # Compute Lij applying dynamic modules function
    compute_Lij(u=u_CG1, uf=u_filtered, **vars())

    # Compute Mij applying dynamic modules function
    alpha = 2.5
    magS = compute_Mij(alphaval=alpha, u_nf=u_ab, u_f=u_filtered_CG2, **vars())

    # Lagrange average Lij and Mij
    lagrange_average(J1=JLM, J2=JMM, Aij=Lij, Bij=Mij, **vars())

    # Update Cs = JLM/JMM and filter/smooth Cs
    Cs.vector().set_local((JLM.vector().array()/JMM.vector().array()).clip(max=0.1))
    Cs.vector().apply("insert")

    # Update nut_
    nut_()
