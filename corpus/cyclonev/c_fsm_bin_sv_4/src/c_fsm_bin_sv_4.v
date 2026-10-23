module c_fsm_bin_sv_4 (input logic clk, rst, go, alt, output logic done, odd);
  typedef enum logic [1:0] {S0 = 2'd0, S1 = 2'd1, S2 = 2'd2, S3 = 2'd3} state_t;
  state_t st, nx;
  always_comb begin
    nx = S0;
    case (st)
      S0: begin
        if (go) nx = S1;
        else nx = S0;
      end
      S1: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S2;
        else nx = S1;
      end
      S2: begin
        if (go) nx = S3;
        else nx = S2;
      end
      S3: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S0;
        else nx = S3;
      end
      default: nx = S0;
    endcase
  end
  always_ff @(posedge clk) if (rst) st <= S0; else st <= nx;
  assign done = (st == S3);
  assign odd = (st == S1) | (st == S3);
endmodule
