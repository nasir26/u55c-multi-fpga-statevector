OPENQASM 2.0;
include "qelib1.inc";
gate ccircuit_262450 q0,q1,q2,q3,q4 { ccx q0,q3,q4; ccx q0,q4,q3; ccx q0,q3,q4; ccx q0,q2,q3; ccx q0,q3,q2; ccx q0,q2,q3; ccx q0,q1,q2; ccx q0,q2,q1; ccx q0,q1,q2; cx q0,q1; cx q0,q2; cx q0,q3; cx q0,q4; }
gate ccircuit_262458 q0,q1,q2,q3,q4 { ccx q0,q3,q4; ccx q0,q4,q3; ccx q0,q3,q4; ccx q0,q2,q3; ccx q0,q3,q2; ccx q0,q2,q3; ccx q0,q1,q2; ccx q0,q2,q1; ccx q0,q1,q2; cx q0,q1; cx q0,q2; cx q0,q3; cx q0,q4; ccx q0,q3,q4; ccx q0,q4,q3; ccx q0,q3,q4; ccx q0,q2,q3; ccx q0,q3,q2; ccx q0,q2,q3; ccx q0,q1,q2; ccx q0,q2,q1; ccx q0,q1,q2; cx q0,q1; cx q0,q2; cx q0,q3; cx q0,q4; }
gate ccircuit_262466 q0,q1,q2,q3,q4 {  }
gate ccircuit_262473 q0,q1,q2,q3,q4 {  }
gate ccircuit_262480 q0,q1,q2,q3,q4 {  }
gate ccircuit_262487 q0,q1,q2,q3,q4 {  }
gate ccircuit_262494 q0,q1,q2,q3,q4 {  }
gate ccircuit_262501 q0,q1,q2,q3,q4 {  }
qreg q[12];
h q[0];
h q[1];
h q[2];
h q[3];
h q[4];
h q[5];
h q[6];
h q[7];
x q[8];
ccircuit_262450 q[0],q[8],q[9],q[10],q[11];
ccircuit_262458 q[1],q[8],q[9],q[10],q[11];
ccircuit_262466 q[2],q[8],q[9],q[10],q[11];
ccircuit_262473 q[3],q[8],q[9],q[10],q[11];
ccircuit_262480 q[4],q[8],q[9],q[10],q[11];
ccircuit_262487 q[5],q[8],q[9],q[10],q[11];
ccircuit_262494 q[6],q[8],q[9],q[10],q[11];
ccircuit_262501 q[7],q[8],q[9],q[10],q[11];
swap q[3],q[4];
swap q[2],q[5];
swap q[1],q[6];
swap q[0],q[7];
h q[0];
cp(-pi/2) q[1],q[0];
h q[1];
cp(-pi/4) q[2],q[0];
cp(-pi/2) q[2],q[1];
h q[2];
cp(-pi/8) q[3],q[0];
cp(-pi/4) q[3],q[1];
cp(-pi/2) q[3],q[2];
h q[3];
cp(-pi/16) q[4],q[0];
cp(-pi/8) q[4],q[1];
cp(-pi/4) q[4],q[2];
cp(-pi/2) q[4],q[3];
h q[4];
cp(-pi/32) q[5],q[0];
cp(-pi/16) q[5],q[1];
cp(-pi/8) q[5],q[2];
cp(-pi/4) q[5],q[3];
cp(-pi/2) q[5],q[4];
h q[5];
cp(-pi/64) q[6],q[0];
cp(-pi/32) q[6],q[1];
cp(-pi/16) q[6],q[2];
cp(-pi/8) q[6],q[3];
cp(-pi/4) q[6],q[4];
cp(-pi/2) q[6],q[5];
h q[6];
cp(-pi/128) q[7],q[0];
cp(-pi/64) q[7],q[1];
cp(-pi/32) q[7],q[2];
cp(-pi/16) q[7],q[3];
cp(-pi/8) q[7],q[4];
cp(-pi/4) q[7],q[5];
cp(-pi/2) q[7],q[6];
h q[7];