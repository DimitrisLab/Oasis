__author__ = 'Mikael Mortensen <mikaem@math.uio.no>'
__date__ = '2015-01-22'
__copyright__ = 'Copyright (C) 2015 ' + __author__
__license__  = 'GNU Lesser GPL version 3 or any later version'

from dolfin import Function, FunctionSpace, assemble, TestFunction, sym, grad, tr, \
    Identity, dx, inner, Max, DirichletBC, Constant, dev

from common import derived_bcs

__all__ = ['les_setup', 'les_update']

def les_setup(u_, mesh, Wale, bcs, CG1Function, nut_krylov_solver, **NS_namespace):
    """Set up for solving Wale LES model
    """
    DG = FunctionSpace(mesh, "DG", 0)
    CG1 = FunctionSpace(mesh, "CG", 1)

    delta = Function(DG)
    delta.vector().zero()
    delta.vector().axpy(1.0, assemble(TestFunction(DG)*dx))

    Sij = sym(grad(u_))
    Gij = grad(u_)
    dim = mesh.geometry().dim()

    Sd = sym(Gij*Gij) - (1./dim)*Identity(dim)*tr(Gij*Gij)
    nut_form = Wale['Cw']**2 * pow(delta, 2./dim) * pow(inner(Sd, Sd), 1.5) / (pow(inner(Sij, Sij), 2.5) + pow(inner(Sd, Sd), 1.25))
    bcs_nut = derived_bcs(CG1, bcs['u0'], u_)
    nut_ = CG1Function(nut_form, mesh, method=nut_krylov_solver, bcs=bcs_nut, name='nut', bounded=True)
    
    return dict(Sij=Sij, Sd=Sd, nut_=nut_, delta=delta, bcs_nut=bcs_nut)
    
def les_update(nut_, tstep, **NS_namespace):
    """Compute nut_"""
    if tstep > 1:
        nut_()
