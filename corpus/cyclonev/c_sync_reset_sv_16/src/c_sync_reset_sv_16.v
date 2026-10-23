module c_sync_reset_sv_16 (input logic clk, rst, input logic [15:0] d, output logic [15:0] q);
  always_ff @(posedge clk) if (rst) q <= '0; else q <= d;
endmodule
