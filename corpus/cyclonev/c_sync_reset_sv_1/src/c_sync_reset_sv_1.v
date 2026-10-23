module c_sync_reset_sv_1 (input logic clk, rst, input logic [0:0] d, output logic [0:0] q);
  always_ff @(posedge clk) if (rst) q <= '0; else q <= d;
endmodule
