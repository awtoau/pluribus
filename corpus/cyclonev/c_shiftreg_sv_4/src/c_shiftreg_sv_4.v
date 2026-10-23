module c_shiftreg_sv_4 (input logic clk, input logic d, output logic [3:0] q);
  genvar i;
  generate for (i = 0; i < 4; i++) begin : g
    if (i == 0) begin : first
      always_ff @(posedge clk) q[i] <= d;
    end
    else begin : rest
      always_ff @(posedge clk) q[i] <= q[i-1];
    end
  end endgenerate
endmodule
