OPENQASM 2.0;
include "qelib1.inc";
gate ccircuit_262514 q0,q1,q2,q3,q4 { ccx q0,q3,q4; ccx q0,q4,q3; ccx q0,q3,q4; ccx q0,q2,q3; ccx q0,q3,q2; ccx q0,q2,q3; ccx q0,q1,q2; ccx q0,q2,q1; ccx q0,q1,q2; cx q0,q1; cx q0,q2; cx q0,q3; cx q0,q4; }
gate ccircuit_262522 q0,q1,q2,q3,q4 { ccx q0,q3,q4; ccx q0,q4,q3; ccx q0,q3,q4; ccx q0,q2,q3; ccx q0,q3,q2; ccx q0,q2,q3; ccx q0,q1,q2; ccx q0,q2,q1; ccx q0,q1,q2; cx q0,q1; cx q0,q2; cx q0,q3; cx q0,q4; ccx q0,q3,q4; ccx q0,q4,q3; ccx q0,q3,q4; ccx q0,q2,q3; ccx q0,q3,q2; ccx q0,q2,q3; ccx q0,q1,q2; ccx q0,q2,q1; ccx q0,q1,q2; cx q0,q1; cx q0,q2; cx q0,q3; cx q0,q4; }
gate ccircuit_262530 q0,q1,q2,q3,q4 {  }
gate ccircuit_262537 q0,q1,q2,q3,q4 {  }
gate ccircuit_262544 q0,q1,q2,q3,q4 {  }
gate ccircuit_262551 q0,q1,q2,q3,q4 {  }
gate ccircuit_262558 q0,q1,q2,q3,q4 {  }
gate ccircuit_262565 q0,q1,q2,q3,q4 {  }
gate ccircuit_262572 q0,q1,q2,q3,q4 {  }
gate ccircuit_262579 q0,q1,q2,q3,q4 {  }
gate ccircuit_262586 q0,q1,q2,q3,q4 {  }
gate ccircuit_262593 q0,q1,q2,q3,q4 {  }
qreg q[16];
h q[0];
h q[1];
h q[2];
h q[3];
h q[4];
h q[5];
h q[6];
h q[7];
h q[8];
h q[9];
h q[10];
h q[11];
x q[12];
ccircuit_262514 q[0],q[12],q[13],q[14],q[15];
ccircuit_262522 q[1],q[12],q[13],q[14],q[15];
ccircuit_262530 q[2],q[12],q[13],q[14],q[15];
ccircuit_262537 q[3],q[12],q[13],q[14],q[15];
ccircuit_262544 q[4],q[12],q[13],q[14],q[15];
ccircuit_262551 q[5],q[12],q[13],q[14],q[15];
ccircuit_262558 q[6],q[12],q[13],q[14],q[15];
ccircuit_262565 q[7],q[12],q[13],q[14],q[15];
ccircuit_262572 q[8],q[12],q[13],q[14],q[15];
ccircuit_262579 q[9],q[12],q[13],q[14],q[15];
ccircuit_262586 q[10],q[12],q[13],q[14],q[15];
ccircuit_262593 q[11],q[12],q[13],q[14],q[15];
swap q[5],q[6];
swap q[4],q[7];
swap q[3],q[8];
swap q[2],q[9];
swap q[1],q[10];
swap q[0],q[11];
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
cp(-pi/256) q[8],q[0];
cp(-pi/128) q[8],q[1];
cp(-pi/64) q[8],q[2];
cp(-pi/32) q[8],q[3];
cp(-pi/16) q[8],q[4];
cp(-pi/8) q[8],q[5];
cp(-pi/4) q[8],q[6];
cp(-pi/2) q[8],q[7];
h q[8];
cp(-pi/512) q[9],q[0];
cp(-pi/1024) q[10],q[0];
cp(-pi/2048) q[11],q[0];
cp(-pi/256) q[9],q[1];
cp(-pi/512) q[10],q[1];
cp(-pi/1024) q[11],q[1];
cp(-pi/128) q[9],q[2];
cp(-pi/256) q[10],q[2];
cp(-pi/512) q[11],q[2];
cp(-pi/64) q[9],q[3];
cp(-pi/128) q[10],q[3];
cp(-pi/256) q[11],q[3];
cp(-pi/32) q[9],q[4];
cp(-pi/64) q[10],q[4];
cp(-pi/128) q[11],q[4];
cp(-pi/16) q[9],q[5];
cp(-pi/32) q[10],q[5];
cp(-pi/64) q[11],q[5];
cp(-pi/8) q[9],q[6];
cp(-pi/16) q[10],q[6];
cp(-pi/32) q[11],q[6];
cp(-pi/4) q[9],q[7];
cp(-pi/8) q[10],q[7];
cp(-pi/16) q[11],q[7];
cp(-pi/2) q[9],q[8];
cp(-pi/4) q[10],q[8];
cp(-pi/8) q[11],q[8];
h q[9];
cp(-pi/2) q[10],q[9];
h q[10];
cp(-pi/4) q[11],q[9];
cp(-pi/2) q[11],q[10];
h q[11];