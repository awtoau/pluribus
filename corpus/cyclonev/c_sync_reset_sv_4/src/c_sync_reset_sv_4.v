module c_sync_reset_sv_4 (input logic clk, rst, input logic [3:0] d, output logic [3:0] q);
  always_ff @(posedge clk) if (rst) q <= '0; else q <= d;
endmodule
