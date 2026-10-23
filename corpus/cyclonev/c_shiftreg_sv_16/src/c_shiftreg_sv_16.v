module c_shiftreg_sv_16 (input logic clk, input logic d, output logic [15:0] q);
  genvar i;
  generate for (i = 0; i < 16; i++) begin : g
    if (i == 0) begin : first
      always_ff @(posedge clk) q[i] <= d;
    end
    else begin : rest
      always_ff @(posedge clk) q[i] <= q[i-1];
    end
  end endgenerate
endmodule
