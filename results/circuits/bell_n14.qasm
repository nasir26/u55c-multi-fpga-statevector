OPENQASM 2.0;
include "qelib1.inc";
qreg q[14];
h q[0];
cx q[0],q[13];